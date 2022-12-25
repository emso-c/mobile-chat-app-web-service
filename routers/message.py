
from fastapi import APIRouter, Request
from config import PING_INTERVAL, STREAM_DELAY
from db import DBAdapter, DBEngine
import asyncio
from sse_starlette.sse import EventSourceResponse

from schemas.message import Message, MessageSend
from utils import parse_message, parse_user
from session_manager import all_messages, get_recently_received_messages, message_queue

message_router = APIRouter()
db = DBEngine("mobil.db")
adap = DBAdapter(db)

@message_router.post("/send-message/")
async def send_message(message:MessageSend):
    if not message.fromID or not message.toID or not message.content:
        return {"error": "Invalid parameters"}

    message = Message(fromID=message.fromID, toID=message.toID, content=message.content)
    last_inserted_id = None
    try:
        last_inserted_id = db.add_message(message.fromID, message.toID, message.content)
    except Exception as e:
        return {"error": "Message sending failed", "exception": e.__str__()}

    all_messages.append(message)
    message_queue.append(message)
    return {"id": last_inserted_id}

@message_router.get("/all-messages/")
async def messages_view():
    return adap.get_messages()

@message_router.get("/received-messages/")
async def received_messages_view(_id:int):
    messages = adap.get_all_received_messages(_id)
    return messages

@message_router.get("/received-messages-by-users/")
async def received_messages_by_users_view(_id:int):
    received_messages:list[dict] = adap.get_all_received_messages(_id)
    sent_messages:list[dict] = adap.get_all_sent_messages(_id)
    messages = received_messages + sent_messages
    messages.sort(key=lambda x: x["date"])
    users = {}
    for message in messages:
        if message["fromID"] is _id:
            if message["toID"] not in users:
                user = adap.get_user(message["toID"])
                users[message["toID"]] = {
                    "messages": [],
                    "username": user["name"],
                    "firebase_uid": user["firebase_uid"],
                    "last_message": None,
                    "last_message_date": None,
                    "unseen_messages": 0,
                }
            else:
                if message["seen"] == 0:
                    users[message["toID"]]["unseen_messages"] += 1
                pass
            users[message["toID"]]["messages"].append(message)
            users[message["toID"]]["last_message"] = message["content"]
            users[message["toID"]]["last_message_date"] = message["date"]
        else:
            if message["fromID"] not in users:
                user = adap.get_user(message["fromID"])
                users[message["fromID"]] = {
                    "messages": [],
                    "username": user["name"],
                    "firebase_uid": user["firebase_uid"],
                    "last_message": None,
                    "last_message_date": None,
                    "unseen_messages": 0,
                }
            else:
                if message["seen"] == 0:
                    users[message["fromID"]]["unseen_messages"] += 1
                pass
            users[message["fromID"]]["messages"].append(message)
            users[message["fromID"]]["last_message"] = message["content"]
            users[message["fromID"]]["last_message_date"] = message["date"]
    return users

async def event_generator(request: Request, user_id:int):
    while True:
        if await request.is_disconnected():
            break

        user = adap.get_user(user_id)
        user = parse_user(user)
        for message in get_recently_received_messages(user):
            yield {
                "id": 0,
                "event": "message",
                "data": parse_message(message),
                "retry": 0
            }
            message_queue.remove(message)
        await asyncio.sleep(STREAM_DELAY)

@message_router.get('/message-stream')
async def message_stream(request: Request, _id:int):
    event_source = EventSourceResponse(event_generator(request, _id))
    event_source.ping_interval = PING_INTERVAL
    return event_source
