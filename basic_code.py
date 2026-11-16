import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import logging
import os
from dotenv import load_dotenv
from db import *
from vkclient import VKClient

load_dotenv()
access_token = os.getenv('VK_TOKEN')
app_id = os.getenv('APP_ID')
token = os.getenv('TOKEN')
group_id = os.getenv('GROUP_ID')
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

def route_message(vk,client,session, user_id, request):
    """Маршрутизирует команду пользователя к соответствующему обработчику."""
    if request in ("привет", "начать", "старт"):
        handle_start(vk, client, session, user_id)
    elif request == "помощь":
        handle_help(vk, client, session, user_id)
    elif request == "поиск":
        handle_search(vk, client, session, user_id)
    elif request == "далее":
        handle_next(vk, client, session, user_id)
    elif request == "в избранное":
        handle_favorite(vk, client, session, user_id)
    elif request == "в чс":
        handle_blacklist(vk, client, session, user_id)
    elif request == "избранное":
        handle_show_favorite(vk, client, session, user_id)
    elif request == "пока":
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
    longpoll = VkLongPoll(vk,wait=25)


    try:
        for event in longpoll.listen():
            if event.type != VkEventType.MESSAGE_NEW or not event.to_me:
                continue

            user_id = event.user_id
            request = (event.text or "").lower().strip()

            try:
                route_message(vk, client, session, user_id, request)
            except Exception:
                logger.exception(
                    "Error while handling message from user=%s text=%r",
                    user_id, event.text,
                )
                session.rollback()
    except KeyboardInterrupt:
        logger.info("Received Ctrl+C, shutting down...")
    finally:
        session.close()
        engine.dispose()
        logger.info("Bot stopped, resources released")

if __name__ == "__main__":
    main()
