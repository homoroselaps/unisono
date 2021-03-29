#!/usr/bin/env python

from bot_config import get_bot_config

import html
import json
import logging
import traceback
import dataset
import random
import hashlib
import uuid
import datetime
from datetime import timezone

from telegram import (
    ParseMode,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    CallbackQueryHandler,
)

prompts = [
    "Pick up an object around you. What story connects you with it?",
    "Tell a story that made you feel wonder this week!",
    "What great new idea have you learned about recently?",
    "What's your favorite movie and why?",
    'What’s your favorite way to spend a day off?',
    'What was the best vacation you ever took and why?',
    'Where’s the next place on your travel bucket list and why?',
    'What are your hobbies, and how did you get into them?',
    'What was your favorite age growing up?',
    'What was the last thing you read?',
    'What’s your favorite ice cream topping?',
    'What was the last TV show you binge-watched?',
    'Are you into podcasts or do you only listen to music?',
    'If you could only eat one food for the rest of your life, what would it be?',
    'What’s your go-to guilty pleasure?',
    'In the summer, would you rather go to the beach or go camping?',
    'What’s your favorite quote from a TV show/movie/book?',
    'How old were you when you had your first celebrity crush, and who was it?',
    'What’s one thing that can instantly make your day better?',
]

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

db_roaming = dataset.connect('sqlite:///roaming.db')

MINIMUM_VOICE_DURATION = 5

# This can be your own ID, or one for a developer group/channel.
# You can use the /start command of this bot to see your chat id.
DEVELOPER_CHAT_ID = 269701884 #-153553529
bot_config = get_bot_config()

def get_utc_timestamp():
    dt = datetime.datetime.now(timezone.utc)
    utc_time = dt.replace(tzinfo=timezone.utc)
    return utc_time.timestamp()

def removeCmd(str):
    return " ".join(str.split(" ")[1:])

def message_model(message_id, chat_id, data, typ, topic='general', origin='', utc_timestamp=get_utc_timestamp()):
    return dict(chat_id=chat_id, data=data, topic='general', typ=typ, origin=origin, message_id=message_id, utc_timestamp=utc_timestamp)

def user_model(chat_id=0):
    return dict(chat_id=chat_id)

def rating_model(from_id=0, to_id=0, message_id=0, rating=-1, utc_timestamp=get_utc_timestamp()):
    return dict(from_id=from_id, to_id=to_id, message_id=message_id, rating=rating, utc_timestamp=utc_timestamp)

def send_note(bot, chat_id, message_id, data, typ):
    keyboard = [[
        InlineKeyboardButton('Next', callback_data=f'N{message_id}'),
        InlineKeyboardButton('Like', callback_data=f'Y{message_id}')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if typ == 'text':
        bot.send_message(chat_id=chat_id, text=data, reply_markup=reply_markup)
    elif typ == 'voice':
        bot.send_voice(chat_id=chat_id, voice=data, reply_markup=reply_markup)

def send_random_note(bot, chat_id):
    user = db_roaming['user'].find_one(chat_id=chat_id)
    if not user:
        raise(Exception("user unknown"))
    
    message_ids = set([msg['message_id'] for msg in db_roaming['message'].find(chat_id={'not':chat_id})])
    rating_msg_ids = set([rating['message_id'] for rating in db_roaming['rating'].find(from_id=chat_id)])
    message_ids -= rating_msg_ids
    if len(message_ids):
        random_msg_id = random.choice(list(message_ids))
        random_msg = db_roaming['message'].find_one(message_id=random_msg_id)
        if not random_msg:
            raise(Exception("message not found"))
        send_note(bot, chat_id=chat_id, message_id=random_msg_id, data=random_msg['data'], typ=random_msg['typ'])
    else:
        keyboard = [[
            InlineKeyboardButton('Check Again', callback_data=f'M')
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=chat_id, text="There are no messages that you havn't yet seen.", reply_markup=reply_markup) 

def error_handler(update: object, context: CallbackContext) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f'An exception was raised while handling an update\n'
        f'<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}'
        '</pre>\n\n'
        f'<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n'
        f'<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n'
        f'<pre>{html.escape(tb_string)}</pre>'
    )

    # Finally, send the message
    context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=message, parse_mode=ParseMode.HTML)

def rating_yes(update: Update, context: CallbackContext):
    query=update.callback_query
    query.answer()
    
    chat_id = query.message.chat.id
    content = query.data[1:]
    if not content:
        raise(Exception("malformed rating command. no content"))
    message_id = content
    receiver = db_roaming['user'].find_one(chat_id=chat_id)
    if not receiver:
        raise(Exception("invalid chat_id"))
    message = db_roaming['message'].find_one(message_id=message_id)
    if not message:
        raise(Exception("invalid message_id"))
    sender = db_roaming['user'].find_one(chat_id=message['chat_id'])
    if not sender:
        raise(Exception("invalid chat_id connected with message"))
    
    db_roaming['rating'].insert(rating_model(from_id=chat_id, to_id=sender['chat_id'], message_id=message_id, rating=1))
    sender_rating = db_roaming['rating'].find_one(from_id=sender['chat_id'], to_id=chat_id, rating=1)
    mutual_like = True if sender_rating else False
    if mutual_like:
        context.bot.send_message(chat_id=chat_id, text=f"You got a match with: {message['origin']}", parse_mode=ParseMode.HTML)
        text = (
            f"You got a match with: {update.callback_query.from_user.mention_html()}\n"
            f"For you to recall, hear their voice again:"
        )
        context.bot.send_message(chat_id=sender['chat_id'], text=text, parse_mode=ParseMode.HTML)
        receiver_message = db_roaming['message'].find_one(message_id=sender_rating['message_id'])
        context.bot.send_voice(chat_id=sender['chat_id'], voice=receiver_message['data'])
        text = (
            '<i>Any thoughts about Unisono? Tell me in the <a href="https://t.me/Unisono_Feedback">Feedback Group</a></i>'
        )
        context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        context.bot.send_message(chat_id=sender['chat_id'], text=text, parse_mode=ParseMode.HTML)
    
    send_random_note(context.bot, chat_id)

def next_message(update: Update, context: CallbackContext):
    query=update.callback_query
    query.answer()
    chat_id = query.message.chat.id
    send_random_note(context.bot, chat_id)

def rating_no(update: Update, context: CallbackContext):
    query=update.callback_query
    query.answer()
    
    chat_id = query.message.chat.id
    content = query.data[1:]
    if not content:
        raise(Exception("malformed rating command. no content"))
    message_id = content
    
    message = db_roaming['message'].find_one(message_id=message_id)
    if not message:
        raise(Exception("invalid message_id"))
    
    db_roaming['rating'].insert(rating_model(from_id=chat_id, to_id=message['chat_id'], message_id=message_id, rating=-1))
    
    send_random_note(context.bot, update.effective_chat.id)

def handle_msg(update:Update, context: CallbackContext):
    update.message.reply_text(text='Let us hear you wonderful voice.')
    return
    '''
    chat_id = update.effective_chat.id
    user = db_roaming['user'].find_one(chat_id=update.effective_chat.id)
    if not user:
        user = user_model(chat_id=update.effective_chat.id)
        db_roaming['user'].upsert(user, ['chat_id'])
    db_roaming['message'].upsert(message_model(
        chat_id=chat_id,
        typ='text',
        data=update.message.text, 
        origin=update.message.from_user.mention_html()
    ), ['chat_id','topic'])
    update.message.reply_text(text='thx for your personal text note')
    context.bot.send_message(chat_id=chat_id, text="Start listening to others' messages to find a match:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Start', callback_data=f'M')]])) 
    '''

def handle_voice_msg(update:Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if update.message.voice.duration < MINIMUM_VOICE_DURATION:
        text = (
        'Oh this was a bit too short!\n'
        'Please elaborate more.'
        )
        update.message.reply_text(text=text)
        return

    user = db_roaming['user'].find_one(chat_id=chat_id)
    if not user:
        user = user_model(chat_id=update.effective_chat.id)
        db_roaming['user'].upsert(user, ['chat_id'])

    db_roaming['message'].upsert(message_model(
        message_id=uuid.uuid4().hex,
        chat_id=chat_id,
        typ='voice',
        data=update.message.voice.file_id,
        origin=update.message.from_user.mention_html()
    ), ['chat_id','topic'])
    text = (
        'Nice to hear you! What a great voice you have.\n'
        'If you like to replace this message, just send a new one any time.\n'
        '<i>Do you enjoy Unisono? Tell me in the <a href="https://t.me/Unisono_Feedback">Feedback Group</a></i>'
    )
    update.message.reply_text(text=text, parse_mode=ParseMode.HTML)
    context.bot.send_message(chat_id=chat_id, text="Start listening to others' messages to find a match:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Start', callback_data=f'M')]])) 

def stats(update: Update, context: CallbackContext):
    if update.effective_chat.id != DEVELOPER_CHAT_ID: return
    text = (
        f"# of users: {len(db_roaming['user'])}\n"
        f"# of message: {len(db_roaming['message'])}\n"
        f"# of ratings: {len(db_roaming['rating'])}\n"
    )
    update.message.reply_text(text=text)

def reset_ratings(update: Update, context: CallbackContext):
    if update.effective_chat.id != DEVELOPER_CHAT_ID: return
    db_roaming['rating'].delete()
    logger.info("ratings database reset")
    update.message.reply_text("done")

def reset_database(update: Update, context: CallbackContext):
    if update.effective_chat.id != DEVELOPER_CHAT_ID: return
    for table in db_roaming.tables:
        db_roaming[table].delete()
    logger.info("database reset")
    update.message.reply_text("done")

def start(update: Update, context: CallbackContext):
    user = db_roaming['user'].find_one(chat_id=update.effective_chat.id)
    if not user:
        user = user_model(chat_id=update.effective_chat.id)
        db_roaming['user'].upsert(user, ['chat_id'])
    tg_user = update.message.from_user
    text = (
        f'Nice to hear from you {tg_user.first_name} {tg_user.last_name}\n'
        f'Want to find someone you are on the same wavelength with?\n'
        f'Send me a <b>voice message</b> so that others get to know you.\n'
    )
    update.message.reply_text(text=text, parse_mode=ParseMode.HTML)

    context.bot.send_voice(chat_id=update.effective_chat.id, voice=bot_config['welcome_message'])

    text = (
        '<i>Any questions or Feedback? Join the <a href="https://t.me/Unisono_Feedback">Feedback Group</a></i>'
    )
    context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode = ParseMode.HTML)

    text = (
        f'You may use this random prompt as a starter:\n'
        f'<i>{random.choice(prompts)}</i>'
    )
    context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode = ParseMode.HTML)

def main() -> None:
    # Create the Updater and pass it your bot's token.
    updater = Updater(bot_config['bot_token'])

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Register the commands...
    
    dispatcher.add_handler(CommandHandler('start', start))
    if bot_config['dev_mode']:
        dispatcher.add_handler(CommandHandler('reset_ratings', reset_ratings))
        dispatcher.add_handler(CommandHandler('reset_database', reset_database))
    dispatcher.add_handler(CommandHandler('stats', stats))
    dispatcher.add_handler(CallbackQueryHandler(rating_no, pattern='^N'))
    dispatcher.add_handler(CallbackQueryHandler(rating_yes, pattern='^Y'))
    dispatcher.add_handler(CallbackQueryHandler(next_message, pattern='^M'))
    dispatcher.add_handler(MessageHandler(Filters.text, handle_msg))
    dispatcher.add_handler(MessageHandler(Filters.voice, handle_voice_msg))

    # ...and the error handler
    dispatcher.add_error_handler(error_handler)

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    main()
