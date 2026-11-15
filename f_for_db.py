import os
from dotenv import load_dotenv
import sqlalchemy as sq
from sqlalchemy.orm import sessionmaker
from f_for_vk import get_user_info

load_dotenv()

password = os.getenv('PASSWORD')

DSN = f'postgresql://postgres:{password}@localhost:5432/db_vkinder'
engine = sq.create_engine(DSN)

Session = sessionmaker(bind=engine)
session = Session()

#заполнение таблиц
def insert_vk_user(api,user_id): #вставка в таблицу vk_user
    """Заполнение таблицы vk_user"""
    user_info=get_user_info(api,user_id)
    age=user_info.get('age')
    sex=user_info.get('sex')
    city_id=user_info.get('city_id')
    if not age or not sex or not city_id:
        return None
    vk_user=VKUser(id=user_id,age=age,sex=sex,city_id=city_id)
    merged=session.merge(vk_user)
    session.commit()
    return merged

# insert_vk_user(api,user_id)

def insert_candidates(api,user_id): #вставка в таблицу candidates
    """Заполнение таблицы candidates"""
    session = Session()
    try:
        candidates_info = search_candidates(api,user_id) #получаем список кандидатов
        if not candidates_info:
            return []
        # Уже сохранённые vk_id этого владельца
        existing = set(session.execute(select(Candidates.vk_id).where(Candidates.owner_id == user_id)).scalars())
        new_candidates=[]
        for candidate in candidates_info:
            if candidate.get('candidate_id') in existing:
                continue
            # Добавляем в таблицу Candidates
            new_candidates.append(Candidates(vk_id=candidate.get('candidate_id'),
                                             owner_id=user_id,
                                             name=candidate.get('name'),
                                             surname=candidate.get('surname'),
                                             link=candidate.get('link')))
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


def insert_photos(api,user_id): #вставка в таблицу photos
    """Заполнение таблицы photos"""
    session = Session()
    try:
        candidates = session.execute(select(Candidates).where(Candidates.owner_id == user_id)).scalars().all()
        for cand in candidates:
            already = session.execute(select(sq.func.count(Photo.id)).where(Photo.candidate_id == cand.id)).scalar_one()
            if already:
                continue

            for att in get_3_candidate_photo(api, cand.vk_id):
                session.add(Photo(candidate_id=cand.id, attachment=att))
        session.commit()
    except Exception:
        session.rollback()
        raise

def show_next_candidate(vk_user_id, vk,session):
    vk_user = session.get(VKUser, vk_user_id)
    if vk_user is None:
        return None
    blacklisted_ids = (select(BlackList.candidate_id).where(BlackList.vk_user_id == vk_user_id))
    candidate = (session.query(Candidates).filter(Candidates.owner_id == vk_user_id,
                                                  Candidates.id > vk_user.last_shown_id,
                                                  ~Candidates.id.in_(blacklisted_ids))
                 .order_by(Candidates.id)
                 .first())

    if candidate is None:
        return False
    vk_user.last_shown_id = candidate.id
    session.commit()

    # формируем сообщение
    text = (
        f"{candidate.name} {candidate.surname}\n"
        f"{candidate.link}"
    )
    attachment = ",".join(p.attachment for p in candidate.photos)  # "photo...,photo...,photo..."

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

def add_to_favorite(user_id,session):
    favorite_id = session.execute(select(VKUser.last_shown_id).where(VKUser.id == user_id)).scalar_one()
    if not favorite_id:
        return "Нет активного кандидата, начните поиск"
    exiting = session.get(Favorites, (user_id, favorite_id))
    if not exiting:
        favorite = Favorites(vk_user_id=user_id, candidate_id=favorite_id)
        session.add(favorite)
    session.commit()
    return "Кандидат добавлен в избранное"

def add_to_black_list(user_id,session):
    ban_candidate_id = session.execute(select(VKUser.last_shown_id).where(VKUser.id == user_id)).scalar_one()
    if not ban_candidate_id:
        return "Нет активного кандидата, начните поиск"
    exiting = session.get(BlackList, (user_id, ban_candidate_id))
    if not exiting:
        ban_candidate = BlackList(vk_user_id=user_id, candidate_id=ban_candidate_id)
        session.add(ban_candidate)
    session.commit()
    return "Кандидат добавлен в черный список"

def show_favorite_list(user_id,session):
    candidates = session.execute(
        select(Candidates)
        .join(Favorites, Favorites.candidate_id == Candidates.id)
        .where(Favorites.vk_user_id == user_id)
        .options(selectinload(Candidates.photos))    # фото сразу, без N+1
        .order_by(Candidates.id)
    ).scalars().all()

    if not candidates:
        return "Нет избранных кандидатов"

    return candidates
