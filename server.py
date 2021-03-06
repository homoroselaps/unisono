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

questions = [
    "I would like to know",
    "I would like to learn",
    "I always asked myself",
    "I am really curious to know",
    "I am really curious to learn",
    "Humankind pondered over the question",
    "People need to know",
    "People like to know",
    "People want to know",
    "The world needs to know",
]

prompts = [
    "When you pick up an object around you. What story connects you with it?",
    "What is a story that made you feel wonder this week?",
    "What great new idea have you learned about recently?",
    "What's your favorite movie and why?",
    'What’s your favorite way to spend a day off?',
    'What was the best vacation you ever took and why?',
    'Where’s the next place on your travel bucket list and why?',
    'What is a hobby of your\'s, and how did you get into it?',
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

new_message_reaction = [
    "Nice to hear you!",
    "What a great voice you have!",
    "Sonorous!",
    "Your voice is music in my ear.",
    "What a resonant voice you have!",
    "That resonates with me!",
]

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

db_roaming = dataset.connect('sqlite:///roaming.db')

# This can be your own ID, or one for a developer group/channel.
# You can use the /start command of this bot to see your chat id.
bot_config = get_bot_config()

def get_utc_timestamp():
    dt = datetime.datetime.now(timezone.utc)
    utc_time = dt.replace(tzinfo=timezone.utc)
    return utc_time.timestamp()

def removeCmd(str):
    return " ".join(str.split(" ")[1:])

def message_model(message_id, chat_id, data, published=False, topic='general', origin='', utc_timestamp=None):
    if not utc_timestamp:
        utc_timestamp = get_utc_timestamp()
    return dict(chat_id=chat_id, data=data, published=published, topic='general', typ='voice', origin=origin, message_id=message_id, utc_timestamp=utc_timestamp)

def user_model(chat_id=0):
    return dict(chat_id=chat_id)

def rating_model(from_id=0, to_id=0, message_id=0, rating=-1, utc_timestamp=None):
    if not utc_timestamp:
        utc_timestamp = get_utc_timestamp()
    return dict(from_id=from_id, to_id=to_id, message_id=message_id, rating=rating, utc_timestamp=utc_timestamp)

def send_note(bot, chat_id, message_id, data):
    keyboard = [[
        InlineKeyboardButton('Next', callback_data=f'N{message_id}'),
        InlineKeyboardButton('Like', callback_data=f'Y{message_id}')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_voice(chat_id=chat_id, voice=data, reply_markup=reply_markup)

def send_random_note(bot, chat_id):
    user = db_roaming['user'].find_one(chat_id=chat_id)
    if not user:
        raise(Exception("user unknown"))

    rating_msg_ids = set([rating['message_id'] for rating in db_roaming['rating'].find(from_id=chat_id)])
    
    messages = dict()
    query = f"""
    SELECT m.chat_id, m.topic, m.message_id, m.data
    FROM (
        select chat_id, topic, max(utc_timestamp) as max_utc_timestamp
        from message
        where chat_id <> '{chat_id}' and published = '1'
        group by chat_id, topic
    ) as x inner join message as m on m.chat_id = x.chat_id and m.topic = x.topic and m.utc_timestamp = x.max_utc_timestamp;
    """
    for msg in db_roaming.query(query):
        if msg['message_id'] in rating_msg_ids: continue # exclude messages that have been rated before
        messages[msg['message_id']] = msg['data']
    
    if len(messages):
        random_msg_id = random.choice(list(messages.keys()))
        send_note(bot, chat_id=chat_id, message_id=random_msg_id, data=messages[random_msg_id])
    else:
        keyboard = [[
            InlineKeyboardButton('Check Again', callback_data=f'M')
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=chat_id, text="There are no messages that you haven't yet seen.", reply_markup=reply_markup)

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
    context.bot.send_message(chat_id=bot_config['developer_chat_id'], text=message, parse_mode=ParseMode.HTML)

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

    sender_ratings = list(db_roaming['rating'].find(from_id=sender['chat_id'], to_id=chat_id, rating=1))
    mutual_like = True if len(sender_ratings) else False
    if mutual_like:
        text = (
            f"<b>You got a match with: {message['origin']}</b>\n"
            f"Check out their profile and hop on a voice call!"
        )
        context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        
        text = (
            f"<b>You got a match with: {update.callback_query.from_user.mention_html()}</b>\n"
            f"Check out their profile and hop on a voice call!\n"
            f"For you to recall, hear their voice again:"
        )
        context.bot.send_message(chat_id=sender['chat_id'], text=text, parse_mode=ParseMode.HTML)
        for sender_rating_msg_id in set([rating['message_id'] for rating in sender_ratings]):
            receiver_message = db_roaming['message'].find_one(message_id=sender_rating_msg_id)
            context.bot.send_voice(chat_id=sender['chat_id'], voice=receiver_message['data'])
        text = (
            '<i>Any thoughts about Unisono? Tell me in the <a href="https://t.me/Unisono_Feedback">Feedback Group</a></i>'
        )
        context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        context.bot.send_message(chat_id=sender['chat_id'], text=text, parse_mode=ParseMode.HTML)
    else:
        text = (
            "You liked this message.\n"
            "Eager to <b>Share your reaction</b>?\n"
        )
        keyboard = [
            [InlineKeyboardButton('Yes!!', callback_data=f'LRY{message_id}')],
            [InlineKeyboardButton('Check for more messages', callback_data=f'M')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        text = (
            f"Someone just listened to your voice and liked it!"
        )
        context.bot.send_message(chat_id=sender['chat_id'], text=text, parse_mode=ParseMode.HTML)

def like_reaction_yes(update: Update, context: CallbackContext):
    query=update.callback_query
    query.answer()
    message_id = query.data[3:]
    context.chat_data['liked_message_id'] = message_id
    context.bot.send_message(query.message.chat.id, text="Hit the record button now and I'll deliver it directly.")

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

def handle_voice_msg(update:Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if update.message.voice.duration < bot_config['minimum_voice_duration']:
        text = (
        'Oh this was a bit too short!\n'
        '<b>Please elaborate more.</b>'
        )
        update.message.reply_text(text=text, parse_mode=ParseMode.HTML)
        return

    user = db_roaming['user'].find_one(chat_id=chat_id)
    if not user:
        user = user_model(chat_id=update.effective_chat.id)
        db_roaming['user'].upsert(user, ['chat_id'])
    
    message_id = uuid.uuid4().hex

    db_roaming['message'].insert(message_model(
        message_id=message_id,
        chat_id=chat_id,
        published=False,
        data=update.message.voice.file_id,
        origin=update.message.from_user.mention_html()
    ))
    if (chat_id == bot_config['developer_chat_id']):
        update.message.reply_text(text=f'{update.message.voice.file_id}')
    replace_option = len(list(db_roaming['message'].find(chat_id=chat_id, topic='general', published=True))) >= 1

    keyboard = [
        ([InlineKeyboardButton('Send as reaction', callback_data=f'RM{message_id}')] if 'liked_message_id' in context.chat_data else []),
        [
            InlineKeyboardButton('Discard', callback_data=f'DM{message_id}'),
            InlineKeyboardButton(f'{"Replace my message" if replace_option else "Publish"}', callback_data=f'SM{message_id}'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"{random.choice(new_message_reaction)}\n"+
        ("<b>Let's send as reaction to your like?</b>" if 'liked_message_id' in context.chat_data else "<b>Let's publish this as your voice message?</b>")
    )
    update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

def discard_message(update: Update, context: CallbackContext):
    query=update.callback_query
    query.answer()
    
    chat_id = query.message.chat.id
    content = query.data[2:]

    text = (
        "Your message was not published.\n"
        "Simply rewind and <b>Record another take.</b>"
    )
    context.bot.send_message(chat_id=chat_id, text=text, parse_mode = ParseMode.HTML)

def save_message(update: Update, context: CallbackContext):
    query=update.callback_query
    query.answer()
    
    chat_id = query.message.chat.id
    message_id = query.data[2:]

    message = dict(published=True, message_id=message_id, chat_id=chat_id)
    db_roaming['message'].update(message, ['message_id', 'chat_id'])

    text = (
        "Your message can now be discovered.\n"
        "<b>Start listening to others' messages to find a match:</b>"
    )
    context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Start', callback_data=f'M')]]), parse_mode=ParseMode.HTML) 

def react_message(update: Update, context: CallbackContext):
    query=update.callback_query
    query.answer()
    
    chat_id = query.message.chat.id
    message_id = query.data[2:]

    liked_message_id = context.chat_data.get('liked_message_id',None)
    if not liked_message_id: return

    message = db_roaming['message'].find_one(message_id=message_id, chat_id=chat_id, published=False)
    message['topic'] = liked_message_id
    db_roaming['message'].update(message, ['published','message_id', 'chat_id'])
    
    liked_message = db_roaming['message'].find_one(message_id=liked_message_id)

    text = (
        'Here is how they react to your message:'
    )
    context.bot.send_message(liked_message['chat_id'], text)
    
    keyboard = [[
        InlineKeyboardButton('Next', callback_data=f'N{message_id}'),
        InlineKeyboardButton('Like', callback_data=f'Y{message_id}')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.bot.send_voice(liked_message['chat_id'], message['data'], reply_markup=reply_markup)

    text = (
        "Your reaction was delivered directly\n"
    )
    context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Check out more messages', callback_data=f'M')]])) 

def stats(update: Update, context: CallbackContext):
    if update.effective_chat.id != bot_config['developer_chat_id']: return
    text = (
        f"# of users: {len(db_roaming['user'])}\n"
        f"# of message: {len(db_roaming['message'])}\n"
        f"# of ratings: {len(db_roaming['rating'])}\n"
    )
    update.message.reply_text(text=text)

def reset_ratings(update: Update, context: CallbackContext):
    if update.effective_chat.id != bot_config['developer_chat_id']: return
    db_roaming['rating'].delete()
    logger.info("ratings database reset")
    update.message.reply_text("done")

def reset_database(update: Update, context: CallbackContext):
    if update.effective_chat.id != bot_config['developer_chat_id']: return
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
    )
    update.message.reply_text(text=text, parse_mode=ParseMode.HTML)

    context.bot.send_voice(chat_id=update.effective_chat.id, voice=bot_config['welcome_message'])

    text = (
        f'Want to find someone you are on the same wavelength with?\n'
        f'Send me a <b>voice message</b>, so that others get to know you.\n'
        f'If you mutually enjoy each others voice I\'ll put you in touch.\n'
        '\n'
        f'<i>Any Questions or Feedback? Join the <a href="https://t.me/Unisono_Feedback">Feedback Group</a></i>'
    )
    update.message.reply_text(text=text, parse_mode=ParseMode.HTML)

    text = (
        'Start right now. Tell me what excites you or Answer a random prompt:'
    )
    keyboard = [[
        InlineKeyboardButton('Give me a random prompt', callback_data=f'P')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup, parse_mode = ParseMode.HTML)

def random_prompt(update: Update, context: CallbackContext):
    query=update.callback_query
    query.answer()
    
    chat_id = query.message.chat.id
    content = query.data[1:]
    
    count = 0
    try:
        count = max(int(content.lower()),0)
    except (ValueError):
        count = 0

    if count == 0:
        text = (
            f'{random.choice(questions)}:\n'
            f'<i>{random.choice(prompts)}</i>'
        )
        keyboard = [[
            InlineKeyboardButton('Another one', callback_data=f'P{count+1}')
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode = ParseMode.HTML, reply_markup=reply_markup)
    elif count < 3:
        text = (
            f'{random.choice(questions)}:\n'
            f'<i>{random.choice(prompts)}</i>'
        )
        keyboard = [[
            InlineKeyboardButton('Another one, please', callback_data=f'P{count+1}')
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode = ParseMode.HTML, reply_markup=reply_markup)
    elif count >= 3:
        text = (
            f'Still hesitant to record your first voice message?\n'
            f'Recording a voice message may feel awkward at first. That is ok and normal.\n'
            f'If you like, you can hear My thoughts about this topic and Some examples by others.'
        )
        keyboard = [[
            InlineKeyboardButton('More tips please for my first voice message', callback_data=f'F')
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode = ParseMode.HTML, reply_markup=reply_markup)

def send_first_message_help(update: Update, context: CallbackContext):
    if update.effective_chat.id != bot_config['developer_chat_id']: return
    user_ids = set([user['chat_id'] for user in db_roaming['user'].find()])
    message_user_ids = set([msg['chat_id'] for msg in db_roaming['message'].find()])
    user_ids -= message_user_ids

    text = (
        f'<b>I\'m very grateful for you showing interest in Unisono!</b>\n'
        f'Though without a voice message how can others get to know you?\n'
        f'To be frank - you are not the only one. Supporting you to overcome this initial hurdle will make or break the Unisono idea.\n'
        f'<i>If you have any ideas what would help you specifically please reach out. I\'ll be at call in the <a href="https://t.me/Unisono_Feedback">Feedback Group</a>.</i>\n'
        f'In the meantime you can hear my thoughts about this topic or some examples:'
    )
    keyboard = [[
        InlineKeyboardButton('Tips for my first voice message', callback_data=f'F')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    for user_id in user_ids:
        context.bot.send_message(user_id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    context.bot.send_message(update.effective_chat.id, f'Done.\nMessage sent to {len(user_ids)} user(s).')

def first_message_help(update: Update, context: CallbackContext):
    query=update.callback_query
    query.answer()
    
    chat_id = query.message.chat.id
    content = query.data[1:]
    text = (
        f"Why does my voice sound unfamiliar to me when played back?\n"
    )
    context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)
    context.bot.send_voice(chat_id, bot_config['first_message_help'])

    ratings = db_roaming['rating'].find(from_id={'not':chat_id}, to_id={'not':chat_id}, rating=1)
    message_ids = set([msg['message_id'] for msg in ratings])
    if len(message_ids):
        text = (
            f"Curious what others' messages are about?:\n"
        )
        # send first example message
        context.bot.send_message(chat_id, text)
        random_msg_id = random.choice(list(message_ids))
        random_msg = db_roaming['message'].find_one(message_id=random_msg_id)
        if random_msg:
            context.bot.send_voice(chat_id, voice=random_msg['data'])
        message_ids.remove(random_msg_id)
    #send second example message
    if len(message_ids):
        random_msg_id = random.choice(list(message_ids))
        random_msg = db_roaming['message'].find_one(message_id=random_msg_id)
        if random_msg:
            context.bot.send_voice(chat_id, voice=random_msg['data'])
    
    text = (
        "Ready for your first message?\n"
        "Hit record and let's go!"
    )
    context.bot.send_message(chat_id, text)

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
    dispatcher.add_handler(CommandHandler('send_first_message_help', send_first_message_help))
    dispatcher.add_handler(CallbackQueryHandler(rating_no, pattern='^N'))
    dispatcher.add_handler(CallbackQueryHandler(rating_yes, pattern='^Y'))
    dispatcher.add_handler(CallbackQueryHandler(next_message, pattern='^M'))
    dispatcher.add_handler(CallbackQueryHandler(first_message_help, pattern='^F'))
    dispatcher.add_handler(CallbackQueryHandler(random_prompt, pattern='^P'))
    dispatcher.add_handler(CallbackQueryHandler(save_message, pattern='^SM'))
    dispatcher.add_handler(CallbackQueryHandler(discard_message, pattern='^DM'))
    dispatcher.add_handler(CallbackQueryHandler(react_message, pattern='^RM'))
    dispatcher.add_handler(CallbackQueryHandler(like_reaction_yes, pattern='^LRY'))
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
