import sqlalchemy as sq
from sqlalchemy.orm import declarative_base, relationship, sessionmaker,selectinload
from sqlalchemy import select
from random import randrange
from dotenv import load_dotenv
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from methods_vk import *


load_dotenv()
password = os.getenv('PASSWORD')

Base = declarative_base()


class VKUser(Base):
    """Профиль пользователя VK.

    Содержит базовую информацию (возраст, пол, город) для поиска
    кандидатов и историю показов.
    """

    __tablename__ = 'vk_user'

    id = sq.Column(sq.BigInteger, primary_key=True)
    age = sq.Column(sq.Integer, nullable=False)
    sex = sq.Column(sq.Integer, nullable=False)              #для поиска
    city_id = sq.Column(sq.Integer, nullable=False)          #для поиска
    last_shown_id = sq.Column(sq.Integer, nullable=False, default=0)     #для хранения последнего показа

    candidates = relationship('Candidates', backref='owner', cascade='all, delete-orphan')
    favorites  = relationship('Favorites',  backref='user',  cascade='all, delete-orphan')
    blacklist  = relationship('BlackList',  backref='user',  cascade='all, delete-orphan')


class Candidates(Base):
    """Кандидат — сохранённый профиль, найденный для пользователя.

    Содержит данные из VK (имя, фамилия, ссылка) и связи с фото,
    избранным и чёрным списком.
    """

    __tablename__ = 'candidates'

    id = sq.Column(sq.Integer, primary_key=True)
    vk_id = sq.Column(sq.BigInteger, nullable=False)
    owner_id = sq.Column(sq.BigInteger, sq.ForeignKey('vk_user.id', ondelete='CASCADE')) #ссылка на владельца
    name = sq.Column(sq.String(length=40), nullable=False)
    surname = sq.Column(sq.String(length=40), nullable=False)
    link = sq.Column(sq.String, nullable=False)
    # age = sq.Column(sq.Integer)                              #для поиска
    # sex = sq.Column(sq.Integer)                              #для поиска
    # gender = sq.Column(sq.String(length=10))                 #для вывода
    # city = sq.Column(sq.String(length=100))                  #для вывода

    __table_args__ = (
        sq.UniqueConstraint('owner_id', 'vk_id', name='uq_candidate_owner_vk'),
        sq.Index('ix_candidate_owner', 'owner_id'),
    )

    photos = relationship('Photo', backref='candidate',
                          cascade='all, delete-orphan', order_by='Photo.id')
    favorites = relationship('Favorites', backref='candidate',
                             cascade='all, delete-orphan')
    blacklist = relationship('BlackList', backref='candidate',
                             cascade='all, delete-orphan')


class Photo(Base):
    """Фото кандидата (attachment-строка VK API).

    Хранит до 3 самых популярных фото для каждого кандидата.
    """

    __tablename__ = 'photo'

    id = sq.Column(sq.Integer, primary_key=True)
    candidate_id = sq.Column(sq.Integer, sq.ForeignKey('candidates.id', ondelete='CASCADE'), nullable=False)
    attachment = sq.Column(sq.String, nullable=False)

    __table_args__ = (
        sq.UniqueConstraint('candidate_id', 'attachment',
                            name='uq_photo_candidate_attachment'),
        sq.Index('ix_photo_саndidate', 'candidate_id'),
    )



class Favorites(Base):
    """Избранные кандидаты (связующая таблица: пользователь ↔ кандидат).

    Составной первичный ключ (vk_user_id, candidate_id) гарантирует,
    что один кандидат не может быть добавлен в избранное дважды.
    """

    __tablename__ = 'favorites'

    # id = sq.Column(sq.Integer, primary_key=True)
    vk_user_id = sq.Column(sq.BigInteger, sq.ForeignKey('vk_user.id', ondelete='CASCADE'), primary_key=True)
    candidate_id = sq.Column(sq.Integer, sq.ForeignKey('candidates.id', ondelete='CASCADE'), primary_key=True)




class BlackList(Base):
    """Чёрный список кандидатов (связующая таблица: пользователь ↔ кандидат).

    Кандидаты из этого списка исключаются при показе следующих профилей.
    """

    __tablename__ = 'black_list'

    # id = sq.Column(sq.Integer, primary_key=True)
    vk_user_id = sq.Column(sq.BigInteger, sq.ForeignKey('vk_user.id', ondelete='CASCADE'), primary_key=True)
    candidate_id = sq.Column(sq.Integer, sq.ForeignKey('candidates.id', ondelete='CASCADE'), primary_key=True)

    __table_args__ = (
        sq.UniqueConstraint('vk_user_id', 'candidate_id',
                            name='uq_blacklist_user_candidate'),
    )



def create_tables(engine):
    """Создаёт все таблицы в базе данных."""
    # Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

DSN = f'postgresql://postgres:{password}@localhost:5432/db_vkinder'
engine = sq.create_engine(DSN)

create_tables(engine)

Session = sessionmaker(bind=engine)
session = Session()

def insert_vk_user(api, user_id):
    """Создаёт или обновляет профиль пользователя в таблице vk_user.

    Получает данные из VK (возраст, пол, город) через get_user_info.
    Возвращает объект VKUser или None, если данные неполны.
    """
    user_info = get_user_info(api, user_id)
    age = user_info.get('age')
    sex = user_info.get('sex')
    city_id = user_info.get('city_id')
    if not age or not sex or not city_id:
        return None
    vk_user = VKUser(id=user_id, age=age, sex=sex, city_id=city_id)
    merged = session.merge(vk_user)
    session.commit()
    return merged

def insert_candidates(api, user_id):
    """Находит кандидатов через VK API и сохраняет в таблицу candidates.

    Проверяет дубликаты по vk_id для текущего пользователя.
    Возвращает список всех кандидатов пользователя или пустой список.
    """
    session = Session()
    try:
        candidates_info = search_candidates(api, user_id)
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
# insert_candidates(api,user_id)


def insert_photos(api, user_id):
    """Сохраняет до 3 популярных фото для каждого кандидата пользователя.

    Пропускает кандидатов, у которых фото уже сохранены.
    """
    session = Session()
    try:
        candidates = session.execute(
            select(Candidates).where(Candidates.owner_id == user_id)
        ).scalars().all()
        for cand in candidates:
            already = session.execute(
                select(sq.func.count(Photo.id)).where(Photo.candidate_id == cand.id)
            ).scalar_one()
            if already:
                continue
            for att in get_3_candidate_photo(api, cand.vk_id):
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
    attachment = ",".join(p.attachment for p in candidate.photos)

    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("Далее", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("В избранное", color=VkKeyboardColor.POSITIVE)
    keyboard.add_button("В ЧС", color=VkKeyboardColor.NEGATIVE)

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
        print(f"[SNC] send failed for candidate {candidate.id}: {e}")

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
