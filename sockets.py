"""
Real-time chat between a customer and a shop owner, via Flask-SocketIO.

Room naming: "c{customer_id}-s{shop_id}" - so the same two parties
always land back in the same thread, however they got there (from a
product page, an order, or the chat list).

This only handles the *transport*. Access control (only the customer
themself or the shop's owner may join a given room) is checked in
`handle_join` using the Flask session - never trust the room name the
client claims without checking who is actually logged in.
"""

from flask import session, request
from flask_socketio import join_room, leave_room, emit
from datetime import datetime

from extensions import socketio, db
from models import ChatMessage, Shop, Order, User, AppNotification
import support_bot
import manager_bot

_support_admin_rooms = {}


def _can_access_room(room: str) -> bool:
    user_id = session.get("user_id")
    role = session.get("role")
    if not user_id:
        return False
    if not room.startswith("c") or "-s" not in room:
        return False
    try:
        customer_id = int(room[1:room.index("-s")])
        shop_id = int(room[room.index("-s") + 2:])
    except ValueError:
        return False

    if role in ("customer", "taxi"):
        return user_id == customer_id
    if role == "seller":
        shop = db.session.get(Shop, shop_id)
        return bool(shop and shop.owner_id == user_id)
    if role == "admin":
        # Admins may join any support room (Shadow Support shop) or any room for moderation
        shop = db.session.get(Shop, shop_id)
        if shop and shop.name == "Shadow Support":
            return True
        return True  # admin can assist any thread if needed
    return False


def _msg_dict(m):
    reply_preview = None
    if getattr(m, "reply_to_id", None):
        parent = db.session.get(ChatMessage, m.reply_to_id)
        if parent and not getattr(parent, "is_deleted", False):
            body = parent.body or ""
            reply_preview = {
                "id": parent.id,
                "body": (body[:80] + "…") if len(body) > 80 else body,
                "sender_name": parent.sender_name,
                "msg_type": getattr(parent, "msg_type", None) or "text",
            }
    return {
        "id": m.id,
        "body": "This message was deleted" if getattr(m, "is_deleted", False) else m.body,
        "sender_role": m.sender_role,
        "sender_name": m.sender_name,
        "created_at": m.created_at.strftime("%H:%M") if m.created_at else "",
        "msg_type": getattr(m, "msg_type", None) or "text",
        "reply_to_id": getattr(m, "reply_to_id", None),
        "reply_preview": reply_preview,
        "is_read": bool(getattr(m, "is_read", False)),
        "is_edited": bool(getattr(m, "is_edited", False)),
        "is_deleted": bool(getattr(m, "is_deleted", False)),
    }


@socketio.on("join")
def handle_join(data):
    room = data.get("room", "")
    if not _can_access_room(room):
        emit("error", {"message": "Not allowed to join this conversation."})
        return
    join_room(room)

    if session.get("role") == "admin":
        try:
            shop_id = int(room[room.index("-s") + 2:])
            shop = db.session.get(Shop, shop_id)
            if shop and shop.name == "Shadow Support":
                _support_admin_rooms.setdefault(request.sid, set()).add(room)
                emit("support_human_online", {"online": True}, room=room)
                # Notify room that AI pauses when admin is present
                try:
                    if session.get("role") == "admin":
                        notice = ChatMessage(
                            room=room,
                            customer_id=int(room[1:room.index("-s")]),
                            shop_id=int(room[room.index("-s") + 2:]),
                            sender_role="admin",
                            sender_name="System",
                            body=support_bot.ADMIN_TAKEOVER_NOTICE,
                            msg_type="text",
                        )
                        db.session.add(notice)
                        db.session.commit()
                        emit("new_message", _msg_dict(notice), room=room)
                except Exception as _e:
                    print("takeover notice", _e)
        except (ValueError, AttributeError):
            pass

    history = (
        ChatMessage.query.filter_by(room=room)
        .order_by(ChatMessage.created_at.asc())
        .limit(2000)
        .all()
    )
    emit("history", {"messages": [_msg_dict(m) for m in history]})
    # Empty support room → bot greeting
    if not history:
        try:
            customer_id = int(room[1:room.index("-s")])
            shop_id = int(room[room.index("-s") + 2:])
            shop = db.session.get(Shop, shop_id)
            if shop and shop.name == "Shadow Support" and session.get("role") in ("customer", "taxi"):
                greet = ChatMessage(
                    room=room, customer_id=customer_id, shop_id=shop_id,
                    sender_role="admin", sender_name="Shadow Bot",
                    body=support_bot.GREETING, msg_type="text",
                )
                db.session.add(greet)
                db.session.commit()
                emit("new_message", _msg_dict(greet), room=room)
        except Exception:
            pass
    # Presence + mark others' messages as read
    role = session.get("role")
    emit("presence", {"status": "online", "role": role}, room=room, include_self=False)
    for m in history:
        if m.sender_role != role and not getattr(m, "is_read", False) and not getattr(m, "is_deleted", False):
            m.is_read = True
            m.read_at = datetime.utcnow()
    db.session.commit()
    emit("messages_read", {"reader_role": role}, room=room, include_self=False)


@socketio.on("join_shop")
def handle_join_shop(data):
    """Lets a logged-in seller's dashboard/orders page subscribe to
    real-time 'new_order' events for their own shop only."""
    shop_id = data.get("shop_id")
    user_id = session.get("user_id")
    if session.get("role") == "seller" and user_id and shop_id:
        shop = db.session.get(Shop, shop_id)
        if shop and shop.owner_id == user_id:
            join_room(f"shop-{shop_id}")


@socketio.on("join_shop_public")
def handle_join_shop_public(data):
    """Public room, no auth needed - product availability is already
    visible to anyone on the shop's public page, so anyone (including
    an anonymous browser) may subscribe to live availability changes."""
    shop_id = data.get("shop_id")
    if shop_id:
        join_room(f"shop-{shop_id}-public")


@socketio.on("join_order")
def handle_join_order(data):
    """Lets a customer's tracking page (or the owning seller) subscribe
    to live status updates for one specific order."""
    order_id = data.get("order_id")
    user_id = session.get("user_id")
    role = session.get("role")
    order = db.session.get(Order, order_id) if order_id else None
    if not order or not user_id:
        return
    if role in ("customer", "taxi") and order.customer_id == user_id:
        join_room(f"order-{order_id}")
    elif role == "seller":
        shop = db.session.get(Shop, order.shop_id)
        if shop and shop.owner_id == user_id:
            join_room(f"order-{order_id}")


@socketio.on("join_customer_updates")
def handle_join_customer_updates():
    """Lets a logged-in customer subscribe to status updates for ALL of
    their own orders app-wide (not just while sitting on one order's
    tracking page) - joined from a global script on every customer page,
    same idea as join_shop for the seller's new-order alerts."""
    user_id = session.get("user_id")
    if session.get("role") in ("customer", "taxi") and user_id:
        join_room(f"customer-{user_id}")


@socketio.on("send_message")
def handle_send_message(data):
    room = data.get("room", "")
    body = (data.get("body") or "").strip()
    msg_type = (data.get("msg_type") or "text").strip()
    if msg_type not in ("text", "voice", "image"):
        msg_type = "text"
    reply_to_id = data.get("reply_to_id")
    if not body or not _can_access_room(room):
        return

    # Images/voice may be large data-URLs; allow more for those
    max_len = 2_000_000 if msg_type in ("image", "voice") else 4000
    body = body[:max_len]

    customer_id = int(room[1:room.index("-s")])
    shop_id = int(room[room.index("-s") + 2:])
    actor = db.session.get(User, session.get("user_id"))
    shop = db.session.get(Shop, shop_id)
    if actor and actor.role != "admin" and msg_type == "text" and manager_bot.contains_link(body):
        duration = manager_bot.apply_link_enforcement(actor, support=bool(shop and shop.name == "Shadow Support"))
        db.session.commit()
        emit("security_block", {"message": manager_bot.ban_message(duration), "banned": True})
        return
    if reply_to_id:
        try:
            reply_to_id = int(reply_to_id)
        except (TypeError, ValueError):
            reply_to_id = None

    msg = ChatMessage(
        room=room, customer_id=customer_id, shop_id=shop_id,
        sender_role=session.get("role"), sender_name=session.get("user_name", "User"),
        body=body, msg_type=msg_type, reply_to_id=reply_to_id,
    )
    db.session.add(msg)
    db.session.commit()

    payload = _msg_dict(msg)
    emit("new_message", payload, room=room)
    # Notify the other party for in-app sound
    emit("chat_notify", {
        "room": room,
        "preview": body[:80] if msg_type == "text" else (msg_type + " message"),
        "sender_name": msg.sender_name,
    }, room=room, include_self=False)
    # Persist in-app notification for the other party (bell list)
    try:
        recipient_id = None
        role = session.get("role")
        if role in ("customer", "taxi"):
            shop = db.session.get(Shop, shop_id)
            if shop:
                recipient_id = shop.owner_id
        elif role in ("seller", "admin"):
            recipient_id = customer_id
        if recipient_id and recipient_id != session.get("user_id"):
            preview = body[:80] if msg_type == "text" else (msg_type + " message")
            db.session.add(AppNotification(
                user_id=recipient_id,
                title=f"Message from {msg.sender_name}",
                body=preview,
                kind="chat",
                link=f"/chat/support/{customer_id}" if role == "admin" else "",
                is_read=False,
            ))
            db.session.commit()
    except Exception as _e:
        print("chat notif skip", _e)

    if session.get("role") == "admin" and msg_type == "text" and support_bot.is_security_call(body):
        report = ChatMessage(
            room=room, customer_id=customer_id, shop_id=shop_id,
            sender_role="admin", sender_name=support_bot.SECURITY_BOT_NAME,
            body=support_bot.security_report(User.query.all()), msg_type="text",
        )
        db.session.add(report)
        db.session.commit()
        emit("new_message", _msg_dict(report), room=room)

    # Support bot: if customer wrote in Shadow Support and no admin replied recently, auto-reply
    if session.get("role") in ("customer", "taxi") and msg_type == "text":
        shop = db.session.get(Shop, shop_id)
        if shop and shop.name == "Shadow Support":
            # A human admin viewing this exact room owns the conversation;
            # otherwise the bot answers immediately, even after old bot text.
            human_online = any(room in rooms for rooms in _support_admin_rooms.values())
            if not human_online:
                # Recent messages as context for AI
                hist_rows = (
                    ChatMessage.query.filter_by(room=room)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(10)
                    .all()
                )
                history = [
                    {"role": m.sender_role, "body": m.body}
                    for m in reversed(hist_rows)
                    if not getattr(m, "is_deleted", False)
                ]
                reply = support_bot.bot_reply(body, history=history)
                bot_msg = ChatMessage(
                    room=room, customer_id=customer_id, shop_id=shop_id,
                    sender_role="admin", sender_name="Shadow AI",
                    body=reply, msg_type="text",
                )
                db.session.add(bot_msg)
                db.session.commit()
                emit("new_message", _msg_dict(bot_msg), room=room)
                emit("chat_notify", {
                    "room": room, "preview": reply[:80],
                    "sender_name": "Shadow Bot", "is_bot": True,
                }, room=room, include_self=False)


@socketio.on("disconnect")
def handle_disconnect():
    rooms = _support_admin_rooms.pop(request.sid, set())
    for room in rooms:
        emit("support_human_online", {"online": False}, room=room)


@socketio.on("edit_message")
def handle_edit_message(data):
    room = data.get("room", "")
    msg_id = data.get("id")
    body = (data.get("body") or "").strip()
    if not body or not msg_id or not _can_access_room(room):
        return
    msg = db.session.get(ChatMessage, int(msg_id))
    if not msg or msg.room != room or msg.sender_role != session.get("role"):
        return
    if msg.is_deleted or msg.msg_type != "text":
        return
    msg.body = body[:4000]
    msg.is_edited = True
    db.session.commit()
    emit("message_edited", _msg_dict(msg), room=room)


@socketio.on("delete_message")
def handle_delete_message(data):
    room = data.get("room", "")
    msg_id = data.get("id")
    if not msg_id or not _can_access_room(room):
        return
    msg = db.session.get(ChatMessage, int(msg_id))
    if not msg or msg.room != room or msg.sender_role != session.get("role"):
        return
    msg.is_deleted = True
    msg.body = ""
    db.session.commit()
    emit("message_deleted", {"id": msg.id}, room=room)


@socketio.on("mark_read")
def handle_mark_read(data):
    room = data.get("room", "")
    if not _can_access_room(room):
        return
    role = session.get("role")
    updated = (
        ChatMessage.query.filter_by(room=room)
        .filter(ChatMessage.sender_role != role)
        .filter((ChatMessage.is_read == False) | (ChatMessage.is_read.is_(None)))  # noqa: E712
        .all()
    )
    for m in updated:
        m.is_read = True
        m.read_at = datetime.utcnow()
    db.session.commit()
    if updated:
        emit("messages_read", {"reader_role": role}, room=room, include_self=False)


@socketio.on("typing")
def handle_typing(data):
    room = data.get("room", "")
    if not _can_access_room(room):
        return
    emit("typing", {
        "role": session.get("role"),
        "name": session.get("user_name", "User"),
        "is_typing": bool(data.get("is_typing")),
    }, room=room, include_self=False)


@socketio.on("presence_ping")
def handle_presence_ping(data):
    room = data.get("room", "")
    if not _can_access_room(room):
        return
    emit("presence", {"status": "online", "role": session.get("role")}, room=room, include_self=False)


@socketio.on("rider_location_update")
def handle_rider_location_update(data):
    """Real live GPS from whoever is currently acting as the rider (the
    seller themself, in this prototype - see README/models.py note on
    there being no separate rider role/app yet). Broadcast straight to
    the order's room so the customer's tracking map can plot the REAL
    position instead of the simulated route animation.

    Only the order's own shop owner may broadcast a position for it -
    never trust the order_id/lat/lng without checking who is sending it."""
    order_id = data.get("order_id")
    lat, lng = data.get("lat"), data.get("lng")
    if order_id is None or lat is None or lng is None:
        return
    if session.get("role") not in ("seller", "taxi"):
        return
    order = db.session.get(Order, order_id)
    if not order:
        return
    shop = db.session.get(Shop, order.shop_id)
    is_shop_owner = shop and shop.owner_id == session.get("user_id")
    is_assigned_driver = order.driver_id == session.get("user_id") and session.get("role") == "taxi"
    if not is_shop_owner and not is_assigned_driver:
        return

    emit("rider_location_live", {"lat": lat, "lng": lng}, room=f"order-{order_id}")


@socketio.on("join_driver")
def handle_join_driver():
    if session.get("role") == "taxi" and session.get("user_id"):
        join_room(f"driver-{session['user_id']}")


@socketio.on("join_user")
def handle_join_user():
    uid = session.get("user_id")
    if uid:
        join_room(f"user-{uid}")
