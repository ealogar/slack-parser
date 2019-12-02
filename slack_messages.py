#!/usr/bin/python
import os
import re
from datetime import datetime
from time import time, sleep
import slack
from slack.errors import SlackApiError

MAX_MESSAGES = 10000  # maximum limit of messages to be checked
regexp_patterns = {}  # internal cache of compiled regexps


def get_users(sc):
    users = {}
    for user in sc.users_list().get('members', []):
        users[user['id']] = user['name'] + "(" + user['profile'].get('first_name', 'Fulano') + ' ' + user[
            'profile'].get('last_name', 'de tal') + "):"
    return users


def get_channel_id(sc, channel_name):
    channel = filter(lambda channel: channel_name == channel['name'], sc.channels_list().get('channels', []))
    try:
        channel_id = list(channel)[0]['id']
    except Exception:
        raise Exception("cannot find channel " + channel_name)
    return channel_id


def _update_posts_by_user(posts_by_user, message):
    if message['user'] in posts_by_user:
        posts_by_user[message['user']]['count'] += 1
        posts_by_user[message['user']]['posts'].append(message)
    else:
        posts_by_user[message['user']] = {'count': 1, 'posts': [message]}


def _update_posts_by_pattern(posts_by_pattern, pattern_found):
    if pattern_found in posts_by_pattern:
        posts_by_pattern[pattern_found]['count'] += 1
    else:
        posts_by_pattern[pattern_found] = {'count': 1}


def apply_filters(msg, reaction_filter, post_regexp_filter):
    if 'user' not in msg:
        return False

    if reaction_filter and len(list(filter(lambda r: r['name'] == reaction_filter, msg.get('reactions', [])))) == 0:
        return False

    if post_regexp_filter:
        if post_regexp_filter not in regexp_patterns:
            regexp_patterns[post_regexp_filter] = re.compile(post_regexp_filter)
        if not regexp_patterns[post_regexp_filter].search(msg['text']):
            return False

    return True


def call_with_rate_control(sc, method, **kwargs):
    try:
        resp = getattr(sc, method)(**kwargs)
    except SlackApiError as e:
        resp = e.response
        if resp['ok'] is False and resp['error'] == 'ratelimited':
            time2sleep = int(resp.headers['retry-after'])
            print("Wait {} second to retry".format(time2sleep))
            sleep(time2sleep)
            resp = getattr(sc, method)(**kwargs)
        else:
            raise e
    return resp


def _include_threads_in_posts(msg, sc, channel_id, post_regexp, posts_by_pattern):
    if 'thread_ts' in msg:
        replies_msg = call_with_rate_control(sc, 'conversations_replies', channel=channel_id, ts=msg['thread_ts'],
                                             limit=1000)
        for rep_msg in replies_msg['messages']:
            # ignore root reply, already taken into account
            if rep_msg['thread_ts'] != rep_msg['ts']:
                pattern_found = regexp_patterns[post_regexp].search(rep_msg['text'])
                if pattern_found:
                    _update_posts_by_pattern(posts_by_pattern, pattern_found.group())


def get_aggregated_posts_by_search(sc, channel_id, date_from, post_regexp):
    """
    Busca todos los posts que cumplan la expresion regular y los agrupa en funcion de lo que se encuentra
    Se incluye busqueda en los primeros 500 replies de cada mensaje
    :param sc:
    :param channel_id:
    :param date_from:
    :param post_regexp:
    :return:
    """
    epoch_time_from = datetime.strptime(date_from, "%d-%m-%Y").timestamp()
    posts_by_pattern = {}
    msg = {}
    if post_regexp not in regexp_patterns:
        regexp_patterns[post_regexp] = re.compile(post_regexp)
    response = call_with_rate_control(sc, 'conversations_history', channel=channel_id, limit=500)
    # page 0
    count_messages = len(response['messages'])
    for msg in response['messages']:
        pattern_found = regexp_patterns[post_regexp].search(msg['text'])
        if pattern_found:
            _update_posts_by_pattern(posts_by_pattern, pattern_found.group())
            # check replies
        _include_threads_in_posts(msg, sc, channel_id, post_regexp, posts_by_pattern)

    not_reached_date_from_limit = True
    while response['has_more'] and count_messages < MAX_MESSAGES and not_reached_date_from_limit:
        response = call_with_rate_control(sc, 'conversations_history', channel=channel_id, limit=500,
                                          cursor=response['response_metadata']['next_cursor'])
        count_messages += len(response['messages'])
        for msg in response['messages']:
            if float(msg['ts']) < epoch_time_from:
                not_reached_date_from_limit = False
                break
            pattern_found = regexp_patterns[post_regexp].search(msg['text'])
            if pattern_found:
                _update_posts_by_pattern(posts_by_pattern, pattern_found.group())
            # check replies
            _include_threads_in_posts(msg, sc, channel_id, post_regexp, posts_by_pattern)

    final_date = datetime.fromtimestamp(float(msg.get('ts', time())))
    print("Consultados {} messages hasta la fecha final de {}".format(count_messages, final_date))
    posts_by_pattern_ordered = {k: v for k, v in sorted(posts_by_pattern.items(), key=sort_func, reverse=True)}
    return posts_by_pattern_ordered


def get_aggregated_posts_by_user(sc, channel_id, date_from, reaction_filter=None, post_regexp_filter=None):
    """
    Consulta todos los posts de un canal y los agrupa por usuarios (no tiene en cuenta threads).
    Si se indicar reaction_filter se eliminan los mensajes que no tenga esa reaction.
    Si ademas se indica post_regexp_filter, se usa esa expresion regular para agrupar mensajes.
    :param post_regexp_filter:
    :param sc:
    :param channel_id:
    :param date_from:
    :param reaction_filter:
    :return:
    """
    epoch_time_from = datetime.strptime(date_from, "%d-%m-%Y").timestamp()
    posts_by_user = {}
    message = {}
    response = call_with_rate_control(sc, 'conversations_history', channel=channel_id, limit=500)
    # page 0
    count_messages = len(response['messages'])
    for message in (msg for msg in response['messages'] if apply_filters(msg, reaction_filter, post_regexp_filter)):
        _update_posts_by_user(posts_by_user, message)
    not_reached_date_from_limit = True
    while response['has_more'] and count_messages < MAX_MESSAGES and not_reached_date_from_limit:
        response = call_with_rate_control(sc, 'conversations_history',channel=channel_id, limit=500,
                                            cursor=response['response_metadata']['next_cursor'])
        count_messages = count_messages + len(response['messages'])
        for message in (msg for msg in response['messages'] if apply_filters(msg, reaction_filter, post_regexp_filter)):
            if float(message['ts']) < epoch_time_from:
                not_reached_date_from_limit = False
                break
            _update_posts_by_user(posts_by_user, message)

    final_date = datetime.fromtimestamp(float(message.get('ts', time())))
    print("Consultados {} messages hasta la fecha final de {}".format(count_messages, final_date))
    posts_by_user_ordered = {k: v for k, v in sorted(posts_by_user.items(), key=sort_func, reverse=True)}
    return posts_by_user_ordered


def sort_func(item):
    return item[1]['count']


def pretty_print_aggregated_posts(users, posts_by_user, channel_name):
    print("Lista de publicadores en el canal {}".format(channel_name))
    for user, count_data in posts_by_user.items():
        print(users[user], 'posted', count_data['count'], 'messages')


def pretty_print_aggregated_users_search_in_channel(posts_by_regexp, users, channel_name):
    print("Lista de mas citados en el canal {}".format(channel_name))
    for user, count_data in posts_by_regexp.items():
        if user and user[1:] in users:  # get rid of @ used in search normally
            print(users[user[1:]], 'mentioned in', count_data['count'], 'messages')
        else:
            print(user[1:], 'mentioned in', count_data['count'], 'messages')


def _has_reaction_in_post(reaction, reactions_list):
    return len(list(filter(lambda r: r['name'] == reaction, reactions_list))) > 0


def _get_reaction_from_reactions_list(reaction, reactions_list):
    r_filtered = next((r for r in reactions_list if r['name'] == reaction), None)
    return r_filtered


def pretty_print_aggregated_posts_reactions(users, posts_by_user, channel_name, reaction):
    """
    Hace un barrido en los posts de cada usuario buscando la reaction indicada e
    imprimiendo totales y los mensajes que han tenido esa reaction
    :param users:
    :param posts_by_user:
    :param channel_name:
    :param reaction:
    :return:
    """
    print("Lista de publicadores en el canal {} con el reaction :{}:".format(channel_name, reaction))
    posts_by_user_reaction = {}
    for k, v in posts_by_user.items():
        posts_with_reactions = list(filter(lambda p: 'reactions' in p, v['posts']))
        posts_with_reaction = list(
            filter(lambda p: _has_reaction_in_post(reaction, p['reactions']), posts_with_reactions))
        if posts_with_reaction:
            reaction_count_pretty = [
                {'msg': msg['text'], 'result': _get_reaction_from_reactions_list(reaction, msg['reactions'])} for msg in
                posts_with_reaction]
            posts_by_user_reaction[k] = {'count': len(posts_with_reaction), 'posts': reaction_count_pretty}

    for user, count_data_reaction in posts_by_user_reaction.items():
        total_reactions = 0
        print(users[user], 'ha tenido un total de', count_data_reaction['count'], "posts con", reaction)
        for post in count_data_reaction['posts']:

            print("------ Post:")
            for line in post['msg'].split('\n'):
                print("{}{}".format(' ' * 8, line))
            print("------ ", reaction, "Count:", post['result']['count'])
            total_reactions += post['result']['count']
        print("------->Total de reacciones", reaction, ": ", total_reactions)
        print()
        print()


def main():
    slack_token = os.environ["SLACK_API_TOKEN"]
    channel_name = os.environ["SLACK_CHANNEL_NAME"]
    channel_name = "test-e2e-tea-nightly"
    date_from = os.environ["SLACK_SEARCH_FROM"]
    date_to = os.environ["SLACK_SEARCH_TO"]
    sc = slack.WebClient(slack_token)
    users = get_users(sc)
    channel_id = get_channel_id(sc, channel_name)
    posts_by_user = get_aggregated_posts_by_user(sc, channel_id, date_from, reaction_filter=None,
                                                post_regexp_filter='nos vamos a salir')
    pretty_print_aggregated_posts(users, posts_by_user, channel_name)
    # Ejemplos de agregados por usuario, incluyendo los mensajes
    # pretty_print_aggregated_posts_reactions(users, posts_by_user, channel_name, 'pimientos')
    # pretty_print_aggregated_posts_reactions(users, posts_by_user, channel_name, 'strike1')
    # pretty_print_aggregated_posts_reactions(users, posts_by_user, channel_name, 'keycap_ten')
    # Sacar listado de personas a las que les citan en un canal y agruparlos por el resultado de la expresion regular
    # posts_with_regexp = get_aggregated_posts_by_search(sc, channel_id, date_from, '@[a-zA-Z0-9]{3,}')
    # pretty_print_aggregated_users_search_in_channel(posts_with_regexp, users, channel_name)


if __name__ == "__main__":
    main()
