import sqlalchemy as sq
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, selectinload
from sqlalchemy import select
import vk_api
import os
from random import randrange
from dotenv import load_dotenv
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from f_for_vk import *

password = os.getenv('PASSWORD')
user = os.getenv('USER')

Base = declarative_base()


class VKUser(Base):
    __tablename__ = 'vk_user'

    id = sq.Column(sq.BigInteger, primary_key=True)
    age = sq.Column(sq.Integer, nullable=False)
    sex = sq.Column(sq.Integer, nullable=False)              #для поиска
    city_id = sq.Column(sq.Integer, nullable=False)          #для поиска
    last_shown_id = sq.Column(sq.Integer, nullable=False,default=0)     #для хранения последнего показа

    candidates = relationship('Candidates', backref='owner', cascade='all, delete-orphan')
    favorites  = relationship('Favorites',  backref='user',  cascade='all, delete-orphan')
    blacklist  = relationship('BlackList',  backref='user',  cascade='all, delete-orphan')


class Candidates(Base):
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
    __tablename__ = 'photo'

    id = sq.Column(sq.Integer, primary_key=True)
    candidate_id = sq.Column(sq.Integer,sq.ForeignKey('candidates.id', ondelete='CASCADE'),nullable=False)
    attachment = sq.Column(sq.String, nullable=False)

    __table_args__ = (
        sq.UniqueConstraint('candidate_id', 'attachment',
                            name='uq_photo_candidate_attachment'),
        sq.Index('ix_photo_саndidate', 'candidate_id'),
    )



class Favorites(Base):
    __tablename__ = 'favorites'

    # id = sq.Column(sq.Integer, primary_key=True)
    vk_user_id = sq.Column(sq.BigInteger, sq.ForeignKey('vk_user.id', ondelete='CASCADE'), primary_key=True)
    candidate_id = sq.Column(sq.Integer, sq.ForeignKey('candidates.id', ondelete='CASCADE'),primary_key=True)


class BlackList(Base):
    __tablename__ = 'black_list'

    # id = sq.Column(sq.Integer, primary_key=True)
    vk_user_id = sq.Column(sq.BigInteger, sq.ForeignKey('vk_user.id', ondelete='CASCADE'), primary_key=True)
    candidate_id = sq.Column(sq.Integer, sq.ForeignKey('candidates.id', ondelete='CASCADE'), primary_key=True)

    __table_args__ = (
        sq.UniqueConstraint('vk_user_id', 'candidate_id',
                            name='uq_blacklist_user_candidate'),
    )


def create_tables(engine):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

DSN = f'postgresql://postgres:{password}@localhost:5432/db_vkinder'
engine = sq.create_engine(DSN)

create_tables(engine)

Session = sessionmaker(bind=engine)
session = Session()

