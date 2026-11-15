import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import os
import logging
from random import randrange
from dotenv import load_dotenv
from classes import ApiVK, DB
from db import session

load_dotenv()
access_token = os.getenv('VK_TOKEN')
app_id = os.getenv('APP_ID')
token = os.getenv('TOKEN')
group_id = os.getenv('GROUP_ID')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)

api = ApiVK(access_token)
db = DB(access_token, session)

vk = vk_api.VkApi(token=token)
longpoll = VkLongPoll(vk,wait=25)

def write_msg(user_id, message, attachment=None, keyboard=None):
    """Отправляет текстовое сообщение пользователю через VK API.

    Поддерживает опциональное прикрепление медиа и клавиатуру.
    """
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

def handle_start(user_id):
    """Отвечает приветствием при команде «привет», «начать», «старт»."""
    write_msg(
        user_id,
        f"Хай, {user_id}. Я бот для поиска второй половины.\n"
        f"Напиши «Поиск», чтобы начать, или «Помощь», чтобы узнать больше.",
    )

def handle_help(user_id):
    """Отправляет описание команд бота по запросу «помощь»."""
    write_msg(
        user_id,
        "Команды:\n"
        "• Поиск — начать поиск\n"
        "• Далее — следующий кандидат\n"
        "• В избранное — сохранить текущего\n"
        "• В ЧС — больше не показывать\n"
        "• Избранное — список сохранённых",
    )

def handle_search(user_id):
    """Запускает процесс поиска кандидатов: заполнение профиля, поиск, показ первого."""
    user = db.insert_vk_user(user_id)
    if user is None:
        write_msg(
            user_id,
            "Нет данных для поиска, заполните, пожалуйста, данные профиля: "
            "пол, возраст, город",
        )
        return
    candidates = db.insert_candidates(user_id)
    db.insert_photos(user_id)
    if not candidates:
        write_msg(user_id, "К сожалению, кандидатов не найдено")
        return
    if db.show_next_candidate(user_id, vk) is False:
        write_msg(user_id, "Кандидаты закончились. Нажмите «Поиск».")

def handle_next(user_id):
    """Показывает следующего кандидата по команде «далее»."""
    if not db.show_next_candidate(vk_user_id=user_id, vk=vk):
        write_msg(user_id, "Кандидаты закончились. Нажмите «Поиск».")
        return

def handle_favorite(user_id):
    """Добавляет текущего кандидата в избранное по команде «в избранное»."""
    msg = db.add_to_favorite(user_id=user_id)
    if msg:
        write_msg(user_id, msg)
    if not db.show_next_candidate(vk_user_id=user_id, vk=vk):
        write_msg(user_id, "Кандидаты закончились. Нажмите «Поиск».")

def handle_blacklist(user_id):
    """Добавляет текущего кандидата в чёрный список по команде «в чс»."""
    msg = db.add_to_black_list(user_id=user_id)
    if msg:
        write_msg(user_id, msg)
    if not db.show_next_candidate(vk_user_id=user_id, vk=vk):
        write_msg(user_id, "Кандидаты закончились. Нажмите «Поиск».")

def handle_show_favorite(user_id):
    """Выводит список избранных кандидатов с фото по команде «избранное»."""
    favorites = db.show_favorite_list(user_id=user_id)
    if not favorites:
        write_msg(user_id, "У вас пока нет избранных кандидатов.")
    else:
        for c in favorites:
            text = f"{c.name} {c.surname}\n{c.link}"
            attachment = ",".join(p.attachment for p in c.photos)
            write_msg(user_id, text, attachment)

def handle_bye(user_id):
    """Прощается с пользователем по команде «пока»."""
    write_msg(user_id, "Пока((")

def route_message(user_id, request):
    """Маршрутизир��ет команду пользователя к соответствующему обработчику."""
    if request in ("привет", "начать", "старт"):
        handle_start(user_id)
    elif request == "помощь":
        handle_help(user_id)
    elif request == "поиск":
        handle_search(user_id)
    elif request == "далее":
        handle_next(user_id)
    elif request == "в избранное":
        handle_favorite(user_id)
    elif request == "в чс":
        handle_blacklist(user_id)
    elif request == "избранное":
        handle_show_favorite(user_id)
    elif request == "пока":
        write_msg(user_id, "Пока((")
    else:
        write_msg(user_id, "Не поняла вашего ответа...")

def main():
    """Точка входа: запускает цикл опроса VK Longpoll для обработки входящих сообщений."""
    for event in longpoll.listen():
        if event.type != VkEventType.MESSAGE_NEW or not event.to_me:
            continue
        user_id = event.user_id
        request = event.text.lower().strip()
        try:
            route_message(user_id, request)
        except Exception:
            logger.exception("Error while handling message from user %s: %r",
                             user_id,
                             event.text,
                             )

if __name__ == "__main__":
    main()
