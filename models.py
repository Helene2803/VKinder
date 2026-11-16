import sqlalchemy as sq
from sqlalchemy.orm import declarative_base, relationship

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

    vk_user_id = sq.Column(sq.BigInteger, sq.ForeignKey('vk_user.id', ondelete='CASCADE'), primary_key=True)
    candidate_id = sq.Column(sq.Integer, sq.ForeignKey('candidates.id', ondelete='CASCADE'), primary_key=True)


class BlackList(Base):
    """Чёрный список кандидатов (связующая таблица: пользователь ↔ кандидат).

    Кандидаты из этого списка исключаются при показе следующих профилей.
    """

    __tablename__ = 'black_list'

    vk_user_id = sq.Column(sq.BigInteger, sq.ForeignKey('vk_user.id', ondelete='CASCADE'), primary_key=True)
    candidate_id = sq.Column(sq.Integer, sq.ForeignKey('candidates.id', ondelete='CASCADE'), primary_key=True)

    __table_args__ = (
        sq.UniqueConstraint('vk_user_id', 'candidate_id',
                            name='uq_blacklist_user_candidate'),
    )

Base = declarative_base()

