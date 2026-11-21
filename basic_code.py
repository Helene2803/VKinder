import logging
import os
from random import randrange

from dotenv import load_dotenv
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType

from db import (make_engine, make_session, create_tables, insert_vk_user, insert_candidates, insert_photos,
                show_next_candidate, add_to_favorite, add_to_black_list, show_favorite_list)
from vkclient import VKClient


load_dotenv()
access_token = os.getenv('VK_TOKEN')
app_id = os.getenv('APP_ID')
token = os.getenv('TOKEN')
group_id = int(os.getenv('GROUP_ID'))
password = os.getenv('PASSWORD')

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

def write_msg(vk,user_id, message, attachment=None, keyboard=None):
    """Отправляет текстовое сообщение пользователю через VK API.
    Поддерживает опциональное прикрепление медиа и клавиатуру.
    """

    params = {
        'user_id': user_id,
        'message': message,
        'random_id': randrange(10**7),
    }
    if attachment:
        params['attachment'] = attachment
    if keyboard:
        params['keyboard'] = keyboard
    try:
        return vk.method('messages.send', params)
    except Exception:
         logger.exception("messages.send failed for user=%s", user_id)
         return None

def handle_start(vk,client,session,user_id):
    """Отвечает приветствием при команде «привет», «начать», «старт»."""
    write_msg(vk,user_id,
        f"Хай, {user_id}. Я бот для поиска второй половины.\n"
        f"Напиши «Поиск», чтобы начать, или «Помощь», чтобы узнать больше.",
    )

def handle_help(vk,client, session, user_id):
    """Отправляет описание команд бота по запросу «помощь»."""
    write_msg(vk,user_id,
        "Команды:\n"
        "• Поиск — начать поиск\n"
        "• Далее — следующий кандидат\n"
        "• В избранное — сохранить текущего\n"
        "• В ЧС — больше не показывать\n"
        "• Избранное — список сохранённых",
    )

def handle_search(vk,client,session,user_id):
    """Запускает процесс поиска кандидатов: заполнение профиля, поиск, показ первого."""
    user = insert_vk_user(client, user_id, session)
    if user is None:
        write_msg(vk,user_id,
            "Нет данных для поиска, заполните, пожалуйста, данные профиля: "
            "пол, возраст, город"
        )
        return
    candidates = insert_candidates(client, user_id, session)
    insert_photos(client, user_id, session)
    logger.info("[handle_search] user=%s saved/total=%d", user_id, len(candidates))
    if not candidates:
        write_msg(vk,user_id, "К сожалению, кандидатов не найдено")
        return
    if show_next_candidate(user_id, vk, session) is False:
        write_msg(vk,user_id, "Кандидаты закончились. Нажмите «Поиск».")

def handle_next(vk, client, session, user_id):
    """Показывает следующего кандидата по команде «далее»."""
    if not show_next_candidate(vk_user_id=user_id, vk=vk,session=session):
        write_msg(vk,user_id, "Кандидаты закончились. Нажмите «Поиск».")
        return

def handle_favorite(vk, client, session, user_id):
    """Добавляет текущего кандидата в избранное по команде «в избранное»."""
    msg = add_to_favorite(user_id=user_id,session=session)
    if msg:
        write_msg(vk,user_id,msg)
    if not show_next_candidate(vk_user_id=user_id, vk=vk,session=session):
        write_msg(vk,user_id, "Кандидаты закончились. Нажмите «Поиск».")

def handle_blacklist(vk, client, session, user_id):
    """Добавляет текущего кандидата в чёрный список по команде «в чс»."""
    msg = add_to_black_list(user_id=user_id,session=session)
    if msg:
        write_msg(vk,user_id, msg)
    if not show_next_candidate(vk_user_id=user_id, vk=vk,session=session):
        write_msg(vk,user_id, "Кандидаты закончились. Нажмите «Поиск».")

def handle_show_favorite(vk, client, session, user_id):
    """Выводит список избранных кандидатов с фото по команде «избранное»."""
    favorites = show_favorite_list(user_id=user_id,session=session)
    if not favorites:
        write_msg(vk,user_id, "У вас пока нет избранных кандидатов.")
    else:
        for c in favorites:
            text = f"{c.name} {c.surname}\n{c.link}"
            attachment = ",".join(p.attachment for p in c.photos)
            write_msg(vk,user_id, text, attachment)

def handle_bye(vk, client, session, user_id):
    """Прощается с пользователем по команде «пока»."""
    write_msg(vk,user_id, "Пока((")

def route_message(vk,client,session, user_id, text):
    """Маршрутизирует команду пользователя к соответствующему обработчику."""
    if text in ("привет", "начать", "старт"):
        handle_start(vk, client, session, user_id)
    elif text == "помощь":
        handle_help(vk, client, session, user_id)
    elif text == "поиск":
        handle_search(vk, client, session, user_id)
    elif text == "далее":
        handle_next(vk, client, session, user_id)
    elif text == "в избранное":
        handle_favorite(vk, client, session, user_id)
    elif text == "в чс":
        handle_blacklist(vk, client, session, user_id)
    elif text == "избранное":
        handle_show_favorite(vk, client, session, user_id)
    elif text == "пока":
        handle_bye(vk, client, session, user_id)
    else:
        write_msg(vk, user_id, "Не поняла вашего ответа...")

def main():
    """Точка входа: запускает цикл опроса VK Longpoll для обработки входящих сообщений."""

    logger.info("Bot is starting (group_id=%s)", group_id)
    # 1. Создаем движок и таблицы БД
    DSN = f'postgresql://postgres:{password}@localhost:5432/db_vkinder'
    engine = make_engine(DSN)
    create_tables(engine)

    #2. Создаем сессию

    SessionFactory = make_session(engine)
    session = SessionFactory()

    #3. Создаем экземпляр класса VKClient для работы с API VK

    client = VKClient(access_token)

    #4. Longpoll

    vk = vk_api.VkApi(token=token)
    longpoll = VkBotLongPoll(vk, group_id)

    logger.info("Listening...")

    # 5.Обработка команд из payload.

    commands = {
        "next":      handle_next,
        "favorite":  handle_favorite,
        "blacklist": handle_blacklist,
    }
    try:
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_EVENT:
                user_id = event.object.user_id
                peer_id = event.object.peer_id
                event_id = event.object.event_id
                payload = event.object.payload
                command = (payload.get("command") or "").strip()

                logger.info("[EVENT] user=%s command=%r payload=%r",
                            user_id, command, payload)

                try:
                    vk.method('messages.sendMessageEventAnswer', {
                        'event_id': event_id,
                        'user_id': user_id,
                        'peer_id': peer_id,
                    })
                except Exception:
                    logger.exception("sendMessageEventAnswer failed")
                handler = commands.get(command)
                if handler is None:
                    logger.warning("[EVENT] unknown command: %r", command)
                    continue
                try:
                    handler(vk, client, session, user_id)
                except Exception:
                    logger.exception("Error handling event user=%s cmd=%r",
                                     user_id, command)
                    session.rollback()
                continue

            # 6. Обработка сообщений.

            if event.type != VkBotEventType.MESSAGE_NEW:
                continue
            user_id = event.object.message.get("from_id")
            if not user_id or user_id < 0:
                continue
            text = (event.object.message.get("text") or "").lower().strip()
            logger.info("[NEW] user=%s text=%r", user_id, text)
            try:
                route_message(vk, client, session, user_id, text)
            except Exception:
                logger.exception("Error handling message user=%s", user_id)
                session.rollback()

    except KeyboardInterrupt:
        logger.info("Ctrl+C, shutting down")
    finally:
        session.close()
        engine.dispose()
        logger.info("Bot stopped")

if __name__ == "__main__":
    main()
