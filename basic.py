import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import os
from random import randrange
from dotenv import load_dotenv
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from classes import ApiVK, DB
from db import session

load_dotenv()
access_token = os.getenv('VK_TOKEN')
# user_id = os.getenv('ID')
app_id = os.getenv('APP_ID')
token = os.getenv('TOKEN')
group_id = os.getenv('GROUP_ID')

api = ApiVK(access_token)
db = DB(access_token)

vk = vk_api.VkApi(token=token)
longpoll = VkLongPoll(vk,wait=25)

def write_msg(user_id, message, attachment=None, keyboard=None):
    # response = vk.method('messages.send', {'user_id': user_id, 'message': message,  'random_id': randrange(10 ** 7),})
    params = {
        'user_id': user_id,
        'message': message,
        'random_id': randrange(10**7),
    }
    if attachment:
        params['attachment'] = attachment
    if keyboard:
        params['keyboard'] = keyboard
    return vk.method('messages.send', params)

# for event in longpoll.listen():
#     if event.type == VkEventType.MESSAGE_NEW and event.to_me:
#         user_id = event.user_id
for event in longpoll.listen():
    if event.type != VkEventType.MESSAGE_NEW or not event.to_me:
        continue

    user_id = event.user_id
    request = event.text.lower().strip()

    if request in ("привет", "начать", "старт"):
        write_msg(user_id,
                  f"Хай, {user_id}. Я бот для поиска второй половины.\n"
                  f"Напиши «Поиск», чтобы начать, или «Помощь», чтобы узнать больше.")

    elif request == "помощь":
        write_msg(user_id,
                  "Команды:\n"
                  "• Поиск — начать поиск\n"
                  "• Далее — следующий кандидат\n"
                  "• В избранное — сохранить текущего\n"
                  "• В ЧС — больше не показывать\n"
                  "• Избранное — список сохранённых")  # TODO: написать блок с описанием функций бота
    elif request == "поиск":
        user = db.insert_vk_user(user_id)
        if user is None:
            write_msg(user_id, "Нет данных для поиска, заполните, пожалуйста данные профиля: пол, возраст, город")
            continue
        candidates = db.insert_candidates(user_id)
        photos = db.insert_photos(user_id)
        if not candidates:
            write_msg(user_id, "К сожалению, кандидатов не найдено")
            continue
        db.show_next_candidate(user_id, vk, session)

    elif request == "далее":
        if not db.show_next_candidate(vk_user_id=user_id, vk=vk, session=session):
            write_msg(user_id, "Кандидаты закончились. Нажмите «Поиск».")

    elif request == "в избранное":
        msg = db.add_to_favorite(session=session, user_id=user_id)
        if msg:
            write_msg(user_id, msg)
        if not db.show_next_candidate(session=session, vk_user_id=user_id, vk=vk):
            write_msg(user_id, "Кандидаты закончились. Нажмите «Поиск».")

    elif request == "в чс":
        msg = db.add_to_black_list(session=session, user_id=user_id)
        if msg:
            write_msg(user_id, msg)
        if not db.show_next_candidate(session=session, vk_user_id=user_id, vk=vk):
            write_msg(user_id, "Кандидаты закончились. Нажмите «Поиск».")

    elif request == "избранное":
        favorites = db.show_favorite_list(session=session, user_id=user_id)
        if not favorites:
            write_msg(user_id, "У вас пока нет избранных кандидатов.")
        else:
            for c in favorites:
                text = f"{c.name} {c.surname}\n{c.link}"
                attachment = ",".join(p.attachment for p in c.photos)
                write_msg(user_id, text, attachment)

    elif request == "пока":
        write_msg(user_id, "Пока((")
    else:
        write_msg(user_id, "Не поняла вашего ответа...")
