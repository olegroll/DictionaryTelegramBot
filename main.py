from flask import Flask
from flask import request
from flask import jsonify
from flask_sslify import SSLify
import requests
import MySQLdb
from keys import yandex_api_key, telegram_token



url = f'https://api.telegram.org/bot{telegram_token}/'
app = Flask(__name__)
sslify = SSLify(app)


def get_yandex_request(word):
    '''Asks for translation from Yandex.Dictionary'''
    request = requests.get('https://dictionary.yandex.net/api/v1/dicservice.json/lookup?',
                           params={
                               'key': yandex_api_key,
                               'lang': 'en-ru',
                               'flags': 0x0004,
                               'text': f'{word}'
                           }
    )
    response = request.json()
    return response


def get_spell_options(word):
    '''Checking for spelling errors in the word. Returns possible options.
    If there are no variants, it returns a message - The value is not found.'''
    request = requests.get(
        f'https://speller.yandex.net/services/spellservice.json/checkText?text={word}'
    )
    response = request.json()
    try:
        word_list = response[0]['s'].remove(word)
    except ValueError:
        word_list = response[0]['s']
    except IndexError:
        return 'Значение не найдено.'
    offer_message = 'Значение не найдено. Возможно вы имели в виду: ' \
                    + ', '.join(word_list) + '?'
    return offer_message


def get_transcription(response):
    '''Returns a transcription of a word or an empty string if it is missing.'''
    try:
        transcription = response['def'][0]['ts']
        return '[' + transcription + ']'
    except IndexError:
        return ''


def make_short_translation(response) -> str:
    '''Forms a standard short translation of the word.'''
    translations = []
    transcription = get_transcription(response)

    for part_of_speech in response['def']:
        counter = 0
        for translation in part_of_speech['tr']:
            translations.append(translation['text'])
            counter += 1
            if counter == 3:
                break
    translations = ', '.join(translations)
    short_answer = transcription + '  ' + translations
    return short_answer


def make_full_translation(response):
    '''Forms a full translation of the word.'''
    full_answer = ''
    transcription = get_transcription(response)

    for part_of_speech in response['def']:
        for translation in part_of_speech['tr']:
            full_answer += translation['text'] + ', '

            try:
                syn_s = [syn['text'] for syn in translation['syn']]
                syn_s = ', '.join(syn_s)
                full_answer += syn_s + ', '
            except KeyError:
                pass

            full_answer = full_answer.rstrip(', ') + ' '

            try:
                mean_s = [mean['text'] for mean in translation['mean']]
                mean_s = ', '.join(mean_s)
                full_answer += '(' + mean_s + ')'
            except KeyError:
                pass

            try:
                if translation['ex']:
                    full_answer += '. Например: '
                for example in translation['ex']:
                    full_answer += example['text'] + ' - '
                    full_answer += example['tr'][0]['text'] + ', '
            except KeyError:
                pass

            full_answer = full_answer.rstrip(', ')
            full_answer += '\n\n'

    full_answer = '[' + transcription + ']\n' + full_answer
    return full_answer


def send_message(chat_id, text='Sample'):
    '''Sends a message to the user.'''
    answer = {'chat_id': chat_id, 'text': text}
    r = requests.post(url + 'sendMessage', json=answer)
    return r.json


def get_stats(current_user_id, current_request_date_time, period):
    '''Generates statistics of requested words for the last week.'''
    db = MySQLdb.connect(user='olegroll', passwd='mangust8',
                         host='olegroll.mysql.pythonanywhere-services.com',
                         db='olegroll$BotDB'
                         )
    cursor = db.cursor()
    sql = 'SELECT word FROM users_requests WHERE user_id = %s and date_time >= %s - %s'
    args = (current_user_id, current_request_date_time, period)
    cursor.execute(sql, args)
    db_response = cursor.fetchall()
    stats = ''
    for item in db_response:
        stats += item[0] + '\n'
    db.close()
    return stats


def check_word_in_db(user_id, request_date_time, message):
    '''Checks if there is a word in the database for the current user_id.'''
    db = MySQLdb.connect(user='user name',      # Your db parameters
                         passwd='password',
                         host='db host',
                         db='db name'
                        )
    cursor = db.cursor()
    sql = 'SELECT * FROM users_requests WHERE word = %s and user_id = %s'
    args = (message, user_id)
    try:
        if cursor.execute(sql, args):
            db.close()
            return True
    except:
        db.rollback()
    db.close()
    return False


def write_to_db(user_id, request_date_time, message):
    '''Writes the current user request into a database.'''
    db = MySQLdb.connect(user='user name',     # Your db parameters
                         passwd='password',
                         host='db host',
                         db='db name'
                        )
    cursor = db.cursor()
    sql = 'INSERT INTO users_requests VALUES (%s,%s,%s)'
    args = (user_id, request_date_time, message)
    try:
        cursor.execute(sql, args)
        db.commit()
    except:
        db.rollback()

    db.close()
    return



@app.route('/', methods=['POST', 'GET'])
def index():
    if request.method == 'POST':
        r = request.get_json()
        chat_id = r['message']['chat']['id']
        user_id = r['message']['from']['id']
        message_text = r['message']['text']
        request_date_time = r['message']['date']

        if '/full' in message_text:
            message_text = message_text.replace('/full', '').strip()
            response = get_yandex_request(message_text)

            if response['def']:    # If the answer from the Yandex is not empty.
                full_translation = make_full_translation(response)
                send_message(chat_id, text=full_translation)
                if not check_word_in_db(user_id, request_date_time, message_text):
                    write_to_db(user_id, request_date_time, message_text)
            else:
                offer_message = get_spell_options(message_text)
                send_message(chat_id, text=offer_message)

        elif '/day' in message_text:
            period = 86400
            db_response = get_stats(user_id, request_date_time, period)
            send_message(chat_id, text=db_response)

        elif '/week' in message_text:
            period = 604800
            db_response = get_stats(user_id, request_date_time, period)
            send_message(chat_id, text=db_response)

        else:                          # Standard short translation of the word.
            message_text= message_text.strip()
            response = get_yandex_request(message_text)

            if response['def']:
                short_translation = make_short_translation(response)
                send_message(chat_id, text=short_translation)
                if not check_word_in_db(user_id, request_date_time, message_text):
                    write_to_db(user_id, request_date_time, message_text)
            else:
                offer_message = get_spell_options(message_text)
                send_message(chat_id, text=offer_message)

        return jsonify(r)
    return 'Test Bot'


if __name__ == '__main__':
    app.run()
