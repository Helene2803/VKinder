import sqlalchemy as sq
import logging
from sqlalchemy.orm import sessionmaker,selectinload
from sqlalchemy import select
from random import randrange
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from models import *

logger = logging.getLogger(__name__)

def make_engine(DSN):
    """Создаёт движок для работы с базой данных."""
    return sq.create_engine(DSN)

def make_session(engine):
    """Создаёт сессию для работы с базой данных."""
    return sessionmaker(bind=engine)

def create_tables(engine):
    """Создаёт все таблицы в базе данных."""
    Base.metadata.create_all(engine)

def insert_vk_user(client, user_id, session):
    """Создаёт или обновляет профиль пользователя в таблице vk_user.
    Получает данные из VK (возраст, пол, город) через get_user_info.
    Возвращает объект VKUser или None, если данные неполны.
    """
    logger.info("insert_vk_user: start user=%s", user_id)

    user_info = client.get_user_info(user_id)
    logger.info("insert_vk_user: user_info=%r", user_info)

    if not user_info:
        logger.warning("insert_vk_user: get_user_info вернул пусто для %s", user_id)
        return None

    age = user_info.get('age')
    sex = user_info.get('sex')
    city_id = user_info.get('city_id')
    logger.info(
        "insert_vk_user: age=%r sex=%r city_id=%r (user=%s)",
        age, sex, city_id, user_id,
    )

    if not age or not sex or not city_id:
        logger.warning(
            "insert_vk_user: не хватает полей для %s. "
            "age=%r, sex=%r, city_id=%r",
            user_id, age, sex, city_id,
        )
        return None

    vk_user = VKUser(id=user_id, age=age, sex=sex, city_id=city_id)
    merged = session.merge(vk_user)
    session.commit()
    logger.info("insert_vk_user: OK, user=%s saved", user_id)
    return merged

def insert_candidates(client, user_id, session):
    """Находит кандидатов через VK API и сохраняет в таблицу candidates.

    Проверяет дубликаты по vk_id для текущего пользователя.
    Возвращает список всех кандидатов пользователя или пустой список.
    """
    try:
        candidates_info = client.search_candidates(user_id)
        if not candidates_info:
            return []
        existing = set(
            session.execute(
                select(Candidates.vk_id).where(Candidates.owner_id == user_id)
            ).scalars()
        )
        new_candidates = []
        for candidate in candidates_info or []:
            if candidate.get('candidate_id') in existing:
                continue
            new_candidates.append(Candidates(
                vk_id=candidate.get('candidate_id'),
                owner_id=user_id,
                name=candidate.get('name'),
                surname=candidate.get('surname'),
                link=candidate.get('link'),
            ))
        if new_candidates:
            session.add_all(new_candidates)
            session.commit()
        return session.execute(
            select(Candidates)
            .where(Candidates.owner_id == user_id)
            .order_by(Candidates.id)
        ).scalars().all()
    except Exception:
        session.rollback()
        raise

def insert_photos(client, user_id_or_candidates, session):
    try:
        if isinstance(user_id_or_candidates, int):
            candidates = session.execute(
                select(Candidates).where(
                    Candidates.owner_id == user_id_or_candidates
                )
            ).scalars().all()
        else:
            candidates = list(user_id_or_candidates or [])

        for cand in candidates:
            already = session.execute(
                select(sq.func.count(Photo.id)).where(
                    Photo.candidate_id == cand.id
                )
            ).scalar_one()
            if already:
                continue

            for att in client.get_3_candidate_photo(cand.vk_id):
                session.add(Photo(candidate_id=cand.id, attachment=att))

        session.commit()
    except Exception:
        session.rollback()
        raise

def show_next_candidate(vk_user_id, vk, session):
    """Показывает следующего кандидата пользователю.

    Выбирает кандидата с id > last_shown_id, исключая из чёрного списка.
    Формирует сообщение с клавиатурой и отправляет через VK API.
    Возвращает True при успехе, False если кандидатов больше нет.
    """
    vk_user = session.get(VKUser, vk_user_id)
    if vk_user is None:
        return None
    blacklisted_ids = (
        select(BlackList.candidate_id).where(BlackList.vk_user_id == vk_user_id)
    )
    candidate = (
        session.query(Candidates)
        .filter(
            Candidates.owner_id == vk_user_id,
            Candidates.id > vk_user.last_shown_id,
            ~Candidates.id.in_(blacklisted_ids),
            )
        .order_by(Candidates.id)
        .first()
    )

    if candidate is None:
        return False
    vk_user.last_shown_id = candidate.id
    session.commit()

    text = (
        f"{candidate.name} {candidate.surname}\n"
        f"{candidate.link}"
    )

    if candidate.photos:
        attachment = ",".join(p.attachment for p in candidate.photos)
    else:
        attachment = None

    keyboard = VkKeyboard(one_time=False)
    keyboard.add_callback_button("Далее", color=VkKeyboardColor.PRIMARY, payload={"command": "next"})
    keyboard.add_callback_button("В избранное", color=VkKeyboardColor.POSITIVE, payload={"command":"favorite"})
    keyboard.add_callback_button("В ЧС", color=VkKeyboardColor.NEGATIVE, payload={"command":"blacklist"})

    params = {
        'user_id': vk_user_id,
        'message': text,
        'keyboard': keyboard.get_keyboard(),
        'random_id': randrange(10**7),
    }
    if attachment:
        params['attachment'] = attachment
    try:
        vk.method('messages.send', params)
    except Exception as e:
        logger.exception("messages.send failed for candidate id=%s", candidate.id)
    return True

def add_to_favorite(user_id, session):
    """Добавляет текущего кандидата в избранное.
    Возвращает текстовое сообщение о результате (успех или ошибка).
    """
    favorite_id = session.execute(
        select(VKUser.last_shown_id).where(VKUser.id == user_id)
    ).scalar_one()
    if not favorite_id:
        return "Нет активного кандидата, начните поиск"
    exiting = session.get(Favorites, (user_id, favorite_id))
    if not exiting:
        favorite = Favorites(vk_user_id=user_id, candidate_id=favorite_id)
        session.add(favorite)
    session.commit()
    return "Кандидат добавлен в избранное"

def add_to_black_list(user_id, session):
    """Добавляет текущего кандидата в чёрный список.
    Возвращает текстовое сообщение о результате (успех или ошибка).
    """
    ban_candidate_id = session.execute(
        select(VKUser.last_shown_id).where(VKUser.id == user_id)
    ).scalar_one()
    if not ban_candidate_id:
        return "Нет активного кандидата, начните поиск"
    exiting = session.get(BlackList, (user_id, ban_candidate_id))
    if not exiting:
        ban_candidate = BlackList(vk_user_id=user_id, candidate_id=ban_candidate_id)
        session.add(ban_candidate)
    session.commit()
    return "Кандидат добавлен в черный список"

def show_favorite_list(user_id, session):
    """Возвращает список избранных кандидатов с их фото.
    Возвращает список объектов Candidates или сообщение "Нет избранных кандидатов".
    """
    candidates = session.execute(
        select(Candidates)
        .join(Favorites, Favorites.candidate_id == Candidates.id)
        .where(Favorites.vk_user_id == user_id)
        .options(selectinload(Candidates.photos))
        .order_by(Candidates.id)
    ).scalars().all()

    if not candidates:
        return "Нет избранных кандидатов"

    return candidates
