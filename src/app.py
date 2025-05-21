import base64
import io
import json
import os
import smtplib
import ssl
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import modal

from db.models import (
    FeedMessage,
    Match,
    Schedule,
    User,
)
from src.helpers import app as helpers_app
from src.helpers import get_schedule_text, rank_users
from utils import (
    APP_NAME,
    GRADUATION_YEARS,
    INTERESTS,
    MAJORS,
    MINORS,
    MINUTES,
    PARENT_PATH,
    PERSONALITY_TRAITS,
    PYTHON_VERSION,
    SECRETS,
)

# -----------------------------------------------------------------------------

# Modal
FE_IMAGE = (
    modal.Image.debian_slim(PYTHON_VERSION)
    .apt_install("git", "libpq-dev")  # add system dependencies
    .pip_install(
        "alembic>=1.15.2",
        "passlib>=1.7.4",
        "pillow>=11.2.1",
        "psycopg2>=2.9.10",
        "python-dotenv>=1.1.0",
        "python-fasthtml>=0.12.12",
        "simpleicons>=7.21.0",
        "sqlmodel>=0.0.24",
        "starlette>=0.46.2",
    )  # add Python dependencies
    .run_commands(
        [
            "git clone https://github.com/Len-Stevens/Python-Antivirus.git /root/Python-Antivirus"
        ]
    )
    .add_local_file(PARENT_PATH / "favicon.ico", "/root/favicon.ico")
    .add_local_file(PARENT_PATH / "logo.png", "/root/logo.png")
)

app = modal.App(APP_NAME)
app.include(helpers_app)

# -----------------------------------------------------------------------------

with FE_IMAGE.imports():
    from fasthtml import common as fh
    from fasthtml.oauth import GitHubAppClient, GoogleAppClient, redir_url
    from passlib.hash import pbkdf2_sha256
    from PIL import Image
    from simpleicons.icons import si_github
    from sqlalchemy import func
    from sqlmodel import Session as DBSession
    from sqlmodel import create_engine, select
    from starlette.middleware.cors import CORSMiddleware


def get_app():  # noqa: C901
    # styles
    font = "font-family:Consolas, Monaco, 'Lucida Console', 'Liberation Mono', 'DejaVu Sans Mono', 'Bitstream Vera Sans Mono', 'Courier New'"
    title_text = "text-4xl font-bold"
    large_text = "text-2xl font-bold"
    medium_text = "text-lg"
    small_text = "text-md"
    xsmall_text = "text-sm"

    text_color = "stone-600"
    text_hover_color = "stone-500"  # for neutral-colored links
    text_button_hover_color = "stone-700"  # for colored buttons
    error_color = "red-400"
    error_hover_color = "red-500"

    img_hover = "opacity-75"

    border_color = "stone-400"
    border_hover_color = "stone-500"

    click_color = "blue-400"
    click_hover_color = "blue-500"
    click_border_color = "blue-600"
    click_border_hover_color = "blue-700"

    click_neutral_color = "stone-50"
    click_neutral_hover_color = "stone-200"
    click_neutral_border_color = "stone-400"
    click_neutral_border_hover_color = "stone-500"

    click_danger_color = "red-400"
    click_danger_hover_color = "red-500"
    click_danger_border_color = "red-600"
    click_danger_border_hover_color = "red-700"

    rounded = "rounded-lg"
    shadow = "shadow-lg"
    shadow_hover = "shadow-md"

    click_button = f"{shadow} hover:{shadow_hover} text-{text_color} hover:text-{text_button_hover_color} bg-{click_color} hover:bg-{click_hover_color} border border-{click_border_color} hover:border-{click_border_hover_color}"
    click_neutral_button = f"{shadow} hover:{shadow_hover} text-{text_color} hover:text-{text_hover_color} bg-{click_neutral_color} hover:bg-{click_neutral_hover_color} border border-{click_neutral_border_color} hover:border-{click_neutral_border_hover_color}"
    click_danger_button = f"{shadow} hover:{shadow_hover} text-{text_color} hover:text-{text_button_hover_color} bg-{click_danger_color} hover:bg-{click_danger_hover_color} border border-{click_danger_border_color} hover:border-{click_danger_border_hover_color}"

    input_bg_color = "stone-50"
    input_cls = f"bg-{input_bg_color} {rounded} {shadow} hover:{shadow_hover} text-{text_color} border border-{border_color} hover:border-{border_hover_color}"

    background_color = "stone-200"
    main_page = f"relative w-full min-h-screen flex flex-col justify-between bg-{background_color} text-{text_color} {font}"
    page_ctnt = "px-8 pb-16 flex grow flex-col justify-center items-center gap-4"

    tailwind_to_hex = {
        click_color: "#60A5FA",
        text_color: "#57534E",
    }
    font_hex = (
        font.split(":")[-1].split(",")[0].strip("'").strip('"')
    )  # Extract just the font family without the CSS property part

    # FastHTML setup
    def before(req, session):
        if "session_id" not in session:
            req.scope["session_id"] = session.setdefault(
                "session_id", str(uuid.uuid4())
            )
        if "user_uuid" not in session:
            req.scope["user_uuid"] = session.setdefault("user_uuid", "")
        if "graduation_year" not in session:
            req.scope["graduation_year"] = session.setdefault("graduation_year", "")
        if "major" not in session:
            req.scope["major"] = session.setdefault("major", "")
        if "minor" not in session:
            req.scope["minor"] = session.setdefault("minor", "")
        if "interests" not in session:
            req.scope["interests"] = session.setdefault("interests", "")
        if "traits" not in session:
            req.scope["traits"] = session.setdefault("traits", "")
        if "schedule_id" not in session:
            req.scope["schedule_id"] = session.setdefault("schedule_id", "")
        if "bio" not in session:
            req.scope["bio"] = session.setdefault("bio", "")
        if "waiting_for_match" not in session:
            req.scope["waiting_for_match"] = session.setdefault(
                "waiting_for_match", False
            )

    def _not_found(session):
        return (
            fh.Title(APP_NAME + " | 404"),
            fh.Div(
                nav(session, "404"),
                fh.Main(
                    fh.P(
                        "Page not found!",
                        cls=f"text-2xl text-{error_color} hover:text-{error_hover_color}",
                    ),
                    cls=page_ctnt,
                ),
                cls=main_page,
            ),
        )

    f_app, _ = fh.fast_app(
        exts="ws",
        before=fh.Beforeware(
            before,
            skip=[
                r"/favicon\.ico",
                r"/static/.*",
                r".*\.css",
            ],
        ),
        exception_handlers={404: _not_found},
        hdrs=[
            fh.Script(src="https://cdn.tailwindcss.com"),
            fh.HighlightJS(langs=["python", "javascript", "html", "css"]),
            fh.Link(rel="icon", href="/favicon.ico", type="image/x-icon"),
            fh.Script(src="https://unpkg.com/htmx-ext-sse@2.2.1/sse.js"),
            fh.Style("""
            .hide-when-loading {
                display: inline-block;
            }
            .htmx-request.hide-when-loading,
            .htmx-request .hide-when-loading {
                display: none;
            }
            .indicator {
                display: none;
            }
            .htmx-request.indicator,
            .htmx-request .indicator {
                display: inline-block;
            }
            """),
        ],
        boost=True,
    )

    f_app.add_middleware(
        CORSMiddleware,
        allow_origins=["/"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # feed
    feed_users = {}

    # db
    engine = create_engine(url=os.getenv("DATABASE_URL"), echo=False)

    @contextmanager
    def get_db_session():
        with DBSession(engine) as session:
            yield session

    def get_curr_user(session):
        if session["user_uuid"]:
            with get_db_session() as db_session:
                query = select(User).where(User.uuid == session["user_uuid"])
                return db_session.exec(query).first()
        return None

    # OAuth
    google_client = GoogleAppClient(
        os.getenv("GOOGLE_CLIENT_ID"), os.getenv("GOOGLE_CLIENT_SECRET")
    )
    github_client = GitHubAppClient(
        os.getenv("GITHUB_CLIENT_ID"), os.getenv("GITHUB_CLIENT_SECRET")
    )

    # ui components
    def spinner(id="", cls=""):
        return (
            fh.Svg(
                fh.NotStr(
                    """<svg class="animate-spin" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" />
                        <path class="opacity-75" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" fill="currentColor" />
                    </svg>"""
                ),
                id=id,
                cls=f"indicator animate-spin {cls}",
            ),
        )

    def schedule_img_container():
        return (
            fh.Label(
                fh.Card(
                    fh.P(
                        "Drag and drop image(s) of your weekly schedule here",
                        cls=f"{large_text} text-{text_color}",
                    ),
                    fh.Input(
                        id="schedule-img-upload",
                        name="schedule_img_file",
                        type="file",
                        accept="image/*",
                        hx_encoding="multipart/form-data",
                        required=True,
                        hx_post="/set-schedule",
                        hx_target="#schedule-img-preview",
                        hx_swap="outerHTML",
                        hx_trigger="change",
                        hx_indicator="#schedule-img-preview, #schedule-img-loader",
                        hx_disabled_elt="#schedule-img-upload, #find-matches-button",
                    ),
                    cls=f"{input_cls} p-8 flex flex-col justify-center items-start gap-8",
                ),
                fh.Div(
                    id="schedule-img-preview",
                ),
                spinner(
                    id="schedule-img-loader",
                    cls=f"absolute bottom-8 right-4 w-6 h-6 text-{text_color} hover:text-{text_hover_color}",
                ),
                id="schedule-img-container",
                hx_swap_oob="true",
                cls="w-full relative",
            ),
        )

    def toast_container(message: str = "", type: str = "", hidden: bool = True):
        return (
            fh.Div(
                fh.P(message, cls=f"text-{text_color} text-center"),
                id="toast-container",
                hx_swap_oob="true",
                cls=f"z-10 absolute top-4 left-1/2 -translate-x-1/2 w-2/3 md:w-1/3 p-4 {rounded} {shadow} "
                + ("hidden " if hidden else "")
                + f"bg-{click_color if type == 'success' else click_danger_color if type == 'error' else click_neutral_color if type == 'info' else ''}",
            ),
            fh.Script(
                """
            setTimeout(() => {
                const toast = document.getElementById('toast-container');
                if (toast) {
                    toast.classList.add('hidden');
                }
            }, 3000);
            """
            ),
        )

    def feed_msgs():
        with get_db_session() as db_session:
            messages = (
                db_session.query(FeedMessage)
                .order_by(FeedMessage.created_at.asc())
                .all()
            )
            return fh.Div(
                *[
                    fh.Div(
                        fh.Div(
                            fh.Div(
                                fh.P(
                                    f"{m.user.username}: ",
                                    cls=f"{small_text} font-semibold text-{text_color} break-all",
                                ),
                                fh.P(
                                    m.created_at.strftime("%b %d, %I:%M %p"),
                                    cls=f"{small_text} text-{text_color} opacity-75",
                                ),
                                cls="flex justify-between items-center gap-4",
                            ),
                            fh.P(
                                m.message,
                                cls=f"{small_text} text-{text_color} break-all",
                            ),
                            cls="flex flex-col gap-1 wrap-break-word",
                        ),
                        cls=f"max-w-full {input_cls} p-4 flex grow justify-between items-start gap-4",
                    )
                    for m in messages
                ]
                if messages
                else [
                    fh.Div(
                        fh.P(
                            "No messages yet. Be the first to say something!",
                            cls=f"{medium_text} text-{text_color} text-center",
                        ),
                        cls=f"w-full {input_cls} p-4 flex justify-center items-center",
                    )
                ],
                id="msg-list",
                cls="w-full flex flex-col justify-center items-start gap-4",
            )

    def feed_input():
        return fh.Textarea(
            id="msg",
            placeholder="Type your message",
            rows=5,
            autofocus=True,
            value="",
            cls=f"{input_cls} p-4 resize-none",
        )

    def settings_profile_img(src: str):
        return fh.Img(
            src=src,
            cls=f"hide-when-loading w-20 h-20 object-cover rounded-full {shadow} cursor-pointer hover:{img_hover}",
            id="profile-img-preview",
        )

    def delete_account_button():
        return (
            fh.Button(
                fh.P(
                    "Delete Account",
                    id="delete-account-button-text",
                    cls=f"hide-when-loading text-{text_color} hover:text-{text_button_hover_color}",
                ),
                spinner(
                    id="delete-account-loader",
                    cls=f"w-6 h-6 text-{text_color} hover:text-{text_button_hover_color}",
                ),
                id="delete-account-button",
                hx_delete="/user/settings/delete-account",
                hx_confirm="Are you sure you want to delete your account? This action cannot be undone.",
                hx_indicator="#delete-account-button-text, #delete-account-loader",
                hx_disabled_elt="#delete-account-button",
                cls=f"w-full flex justify-center items-center {click_danger_button} {rounded} {shadow} p-3",
            ),
        )

    # ui layout
    def nav(session, suffix="", show_auth=True):
        curr_user = get_curr_user(session)
        return fh.Nav(
            fh.Div(
                fh.A(
                    fh.Img(
                        src="/logo.png",
                        cls="w-12 h-12 object-contain",
                    ),
                    fh.P(
                        APP_NAME if not suffix else f"{APP_NAME} — {suffix}",
                        cls=f"{medium_text} text-{text_color}",
                    ),
                    href="/",
                    cls=f"flex justify-center items-center gap-2 hover:{img_hover} hover:text-{text_hover_color}",
                ),
            ),
            overlay(session)
            if curr_user and show_auth
            else fh.Div(
                fh.A(
                    fh.P(
                        "Log In",
                        cls=f"{medium_text} text-{text_color} hover:text-{text_hover_color}",
                    ),
                    href="/login",
                ),
                fh.A(
                    fh.Button(
                        "Sign Up",
                        cls=f"{medium_text} {click_button} {rounded} {shadow} px-4 py-2 whitespace-nowrap",
                    ),
                    href="/signup",
                ),
                cls="flex flex-col md:flex-row justify-center items-end md:items-center gap-8",
            )
            if show_auth
            else None,
            cls="relative px-8 py-16 md:p-20 flex justify-between items-center gap-8",
        )

    def home_content():
        return fh.Main(
            fh.Div(
                fh.H1(
                    "No friends? Find some here!",
                    cls=f"{title_text} text-{text_color} text-center",
                ),
                fh.Form(
                    fh.Div(
                        fh.Select(
                            fh.Option(
                                "-- select graduation year --",
                                disabled="",
                                selected="",
                                value="",
                            ),
                            *[fh.Option(year, value=year) for year in GRADUATION_YEARS],
                            id="graduation-year",
                            name="graduation_year",
                            hx_post="/set-graduation-year",
                            hx_target="this",
                            hx_swap="none",
                            cls=f"w-full {input_cls}",
                            required=True,
                        ),
                        fh.Select(
                            fh.Option(
                                "-- select major --", disabled="", selected="", value=""
                            ),
                            *[fh.Option(major, value=major) for major in MAJORS],
                            id="major",
                            name="major",
                            hx_post="/set-major",
                            hx_target="this",
                            hx_swap="none",
                            cls=f"w-full {input_cls}",
                            required=True,
                        ),
                        fh.Select(
                            fh.Option(
                                "-- select minor (optional) --",
                                disabled="",
                                selected="",
                                value="",
                            ),
                            *[fh.Option(minor, value=minor) for minor in MINORS],
                            id="minor",
                            name="minor",
                            hx_post="/set-minor",
                            hx_target="this",
                            hx_swap="none",
                            cls=f"w-full {input_cls}",
                            required=True,
                        ),
                        fh.Div(
                            fh.H2("Interests", cls=f"{large_text} text-{text_color}"),
                            fh.Div(
                                *[
                                    fh.Div(
                                        fh.Label(
                                            fh.Input(
                                                type="checkbox",
                                                name="interest",
                                                value=interest,
                                                hx_post="/set-interest",
                                                hx_target="this",
                                                hx_swap="none",
                                            ),
                                            interest,
                                            cls=f"text-{text_color} flex justify-start items-center gap-1",
                                        ),
                                        cls="flex justify-start items-center",
                                    )
                                    for interest in INTERESTS
                                ],
                                cls="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2",
                            ),
                            id="interests",
                            cls="w-full flex flex-col gap-4",
                        ),
                        fh.Div(
                            fh.H2(
                                "Personality Traits",
                                cls=f"{large_text} text-{text_color}",
                            ),
                            fh.Div(
                                *[
                                    fh.Div(
                                        fh.Label(
                                            fh.Input(
                                                type="checkbox",
                                                name="trait",
                                                value=trait,
                                                hx_post="/set-trait",
                                                hx_target="this",
                                                hx_swap="none",
                                            ),
                                            trait,
                                            cls=f"text-{text_color} flex justify-start items-center gap-1",
                                        ),
                                        cls="flex justify-start items-center",
                                    )
                                    for trait in PERSONALITY_TRAITS
                                ],
                                cls="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2",
                            ),
                            id="traits",
                            cls="w-full flex flex-col gap-4",
                        ),
                        schedule_img_container(),
                        fh.Label(
                            fh.Textarea(
                                id="bio",
                                placeholder="Bio...",
                                rows=5,
                                hx_post="/set-bio",
                                hx_target="this",
                                hx_swap="none",
                                hx_trigger="change, keyup delay:200ms changed",
                                hx_indicator="#bio-loader",
                                hx_disabled_elt="#find-matches-button",
                                cls=f"{input_cls} p-4 resize-none",
                            ),
                            spinner(
                                id="bio-loader",
                                cls=f"absolute bottom-2 right-2 w-6 h-6 text-{text_color} hover:text-{text_hover_color}",
                            ),
                            cls="w-full relative",
                        ),
                        fh.Button(
                            fh.P(
                                "Please someone good...",
                                id="find-matches-button-text",
                                cls=f"hide-when-loading text-{text_color} hover:text-{text_button_hover_color}",
                            ),
                            spinner(
                                id="find-matches-loader",
                                cls=f"w-6 h-6 text-{text_color} hover:text-{text_button_hover_color}",
                            ),
                            id="find-matches-button",
                            type="submit",
                            cls=f"w-full {click_button} {rounded} {shadow} p-3",
                        ),
                        cls="w-full flex flex-col justify-center items-center gap-8",
                    ),
                    hx_post="/find-matches",
                    hx_target="this",
                    hx_swap="none",
                    hx_indicator="#find-matches-button-text, #find-matches-loader",
                    hx_disabled_elt="#find-matches-button",
                    cls=f"w-full md:w-2/3 {input_cls} p-8",
                ),
                cls="w-full flex flex-col justify-center items-center gap-8",
            ),
            cls=page_ctnt,
        )

    def matches_content(session):
        max_matches = 50
        with get_db_session() as db_session:
            curr_user = get_curr_user(session)
            if curr_user is None:
                return fh.Main(
                    fh.P(
                        "You must be logged in to view your matches.",
                        cls=f"{large_text} text-{text_color} text-center",
                    ),
                    cls=page_ctnt,
                )

            curr_user = db_session.merge(curr_user)  # make relationships accessible
            if curr_user.waiting_for_match:
                fn = rank_users.local if modal.is_local() else rank_users.remote

                users = db_session.exec(
                    select(User)
                    .where(User.uuid != curr_user.uuid)
                    .limit(max_matches)
                    .order_by(func.random())
                ).all()
                if len(users) > 0:
                    user_strs = [str(u) for u in users]
                    ranked_user_strs = fn(
                        str(curr_user),
                        user_strs,
                    )
                    ranked_users = [
                        next(u for u in users if str(u) == user_str)
                        for user_str in ranked_user_strs
                    ]
                    for user in ranked_users:
                        match = Match(user1=curr_user, user2=user)
                        db_session.add(match)
                curr_user.waiting_for_match = False
                db_session.commit()
                db_session.refresh(curr_user)

            matches = curr_user.incoming_matches + curr_user.outgoing_matches
            match_users = []
            seen_user_ids = set()
            for m in matches:
                if len(match_users) >= max_matches:
                    break
                other = m.user1 if m.user1.id != curr_user.id else m.user2
                if other.id not in seen_user_ids:
                    match_users.append(other)
                    seen_user_ids.add(other.id)
            matches = match_users

            if not matches:
                return fh.Main(
                    fh.P(
                        "No matches made yet.",
                        cls=f"{large_text} text-{text_color} text-center",
                    ),
                    cls=page_ctnt,
                )
            return (
                fh.Main(
                    fh.P(
                        "←",
                        id="carousel-left",
                        cls=f"absolute left-4 md:left-60 lg:left-80 top-1/2 -translate-y-1/2 z-10 {large_text} font-bold text-{text_color} hover:text-{text_hover_color} cursor-pointer",
                        onclick="carouselScroll(-1)",
                    ),
                    fh.Div(
                        *[
                            fh.Div(
                                fh.Div(
                                    fh.Img(
                                        src=u.profile_img or "/logo.png",
                                        cls=f"w-48 h-48 object-cover rounded-full {shadow}",
                                    ),
                                    fh.Div(
                                        fh.H2(
                                            u.username or u.email,
                                            cls=f"{large_text} font-bold text-{text_color} text-center",
                                        ),
                                        fh.H3(
                                            u.email if u.username else "",
                                            cls=f"{small_text} text-{text_color} text-center",
                                        ),
                                        cls="flex flex-col justify-center items-center gap-2",
                                    ),
                                    fh.Div(
                                        fh.Div(
                                            fh.P(
                                                "Major",
                                                cls=f"font-semibold text-{text_color}",
                                            ),
                                            fh.P(
                                                f"{u.major or 'Not specified'}",
                                                cls=f"text-{text_color}",
                                            ),
                                            fh.P(
                                                "Minor",
                                                cls=f"font-semibold text-{text_color}",
                                            ),
                                            fh.P(
                                                f"{u.minor or 'Not specified'}",
                                                cls=f"text-{text_color}",
                                            ),
                                            fh.P(
                                                "Graduation",
                                                cls=f"font-semibold text-{text_color}",
                                            ),
                                            fh.P(
                                                f"{u.graduation_year or 'Not specified'}",
                                                cls=f"text-{text_color}",
                                            ),
                                            cls="flex flex-col justify-center items-start gap-2",
                                        ),
                                        fh.Div(
                                            fh.P(
                                                "Interests",
                                                cls=f"font-semibold text-{text_color}",
                                            ),
                                            fh.P(
                                                ", ".join(u.interests)
                                                if u.interests
                                                else "None",
                                                cls=f"italic text-{text_color}",
                                            ),
                                            cls="flex flex-col justify-center items-start gap-2",
                                        ),
                                        fh.Div(
                                            fh.P(
                                                "Personality Traits",
                                                cls=f"font-semibold text-{text_color}",
                                            ),
                                            fh.P(
                                                ", ".join(u.personality_traits)
                                                if u.personality_traits
                                                else "None",
                                                cls=f"italic text-{text_color}",
                                            ),
                                            cls="flex flex-col justify-center items-start gap-2",
                                        ),
                                        fh.Img(
                                            src=u.schedule.img or "/logo.png",
                                            cls="w-60 h-auto md:w-96 md:h-auto object-cover",
                                        ),
                                        fh.Div(
                                            fh.P(
                                                "Bio",
                                                cls=f"font-semibold text-{text_color}",
                                            ),
                                            fh.P(
                                                u.bio,
                                                cls=f"text-{text_color} italic",
                                            ),
                                            cls="flex flex-col justify-center items-start gap-2",
                                        ),
                                        cls=f"{input_cls} p-8 {xsmall_text} flex flex-col gap-4",
                                    ),
                                    cls="flex flex-col justify-start items-center gap-8",
                                ),
                                cls="hidden",  # Hide all cards initially
                            )
                            for u in matches
                        ],
                        id="carousel-inner",
                        cls="w-full md:w-1/3 p-8 flex justify-center items-center gap-4",
                    ),
                    fh.P(
                        "→",
                        id="carousel-right",
                        cls=f"absolute right-4 md:right-60 lg:right-80 top-1/2 -translate-y-1/2 z-10 {large_text} font-bold text-{text_color} hover:text-{text_hover_color} cursor-pointer",
                        onclick="carouselScroll(1)",
                    ),
                    cls=f"{page_ctnt} relative",
                ),
                fh.Script(
                    """
                    let currentIndex = 0;
                    const matches = document.querySelectorAll('#carousel-inner > div');
                    
                    function showCard(index) {
                        // Hide all cards
                        matches.forEach(card => card.style.display = 'none');
                        // Show the current card
                        matches[index].style.display = 'block';
                    }
                    
                    function carouselScroll(dir) {
                        currentIndex = (currentIndex + dir + matches.length) % matches.length;
                        showCard(currentIndex);
                    }
                    
                    // Show first card initially
                    showCard(0);
                    """
                ),
            )

    def feed_content(session):
        curr_user = get_curr_user(session)
        if not curr_user:
            return fh.Main(
                fh.P(
                    "You must be logged in to view the feed.",
                    cls=f"{large_text} text-{text_color} text-center",
                ),
                cls=page_ctnt,
            )
        return fh.Main(
            fh.Div(
                feed_msgs(),
                fh.Form(
                    feed_input(),
                    hx_trigger="keyup[shiftKey&&key=='Enter'] from:body",
                    ws_send=True,
                    cls="w-full relative",
                ),
                hx_ext="ws",
                ws_connect="ws",
                cls=f"w-full md:w-2/3 {input_cls} p-8 flex flex-col justify-start items-center gap-8",
            ),
            cls=page_ctnt,
        )

    def signup_content(req):
        return fh.Main(
            fh.Div(
                fh.H1(
                    "Sign Up",
                    cls=f"{title_text} text-{text_color} text-center",
                ),
                fh.P(
                    fh.Span("(Already have an account? "),
                    fh.A(
                        "Log In",
                        href="/login",
                        cls=f"text-{click_color} hover:text-{click_hover_color}",
                    ),
                    fh.Span(")"),
                    cls=f"text-{text_color} text-center",
                ),
                fh.A(
                    fh.Button(
                        fh.Div(
                            fh.Svg(
                                fh.NotStr(
                                    si_github.svg,
                                ),
                                cls="w-6 h-6",
                            ),
                            fh.Div(
                                "Continue with GitHub",
                                cls="flex grow justify-center items-center",
                            ),
                            cls="flex justify-between items-center gap-4",
                        ),
                        cls=f"w-full {click_neutral_button} p-3 {rounded} {shadow}",
                    ),
                    href=github_client.login_link(redir_url(req, "/redirect-github")),
                    cls="w-full",
                ),
                fh.A(
                    fh.Button(
                        fh.Div(
                            fh.Svg(
                                fh.NotStr(
                                    """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M12.0003 4.75C13.7703 4.75 15.3553 5.36002 16.6053 6.54998L20.0303 3.125C17.9502 1.19 15.2353 0 12.0003 0C7.31028 0 3.25527 2.69 1.28027 6.60998L5.27028 9.70498C6.21525 6.86002 8.87028 4.75 12.0003 4.75Z" fill="#EA4335"/><path d="M23.49 12.275C23.49 11.49 23.415 10.73 23.3 10H12V14.51H18.47C18.18 15.99 17.34 17.25 16.08 18.1L19.945 21.1C22.2 19.01 23.49 15.92 23.49 12.275Z" fill="#4285F4"/><path d="M5.26498 14.2949C5.02498 13.5699 4.88501 12.7999 4.88501 11.9999C4.88501 11.1999 5.01998 10.4299 5.26498 9.7049L1.275 6.60986C0.46 8.22986 0 10.0599 0 11.9999C0 13.9399 0.46 15.7699 1.28 17.3899L5.26498 14.2949Z" fill="#FBBC05"/><path d="M12.0004 24.0001C15.2404 24.0001 17.9654 22.935 19.9454 21.095L16.0804 18.095C15.0054 18.82 13.6204 19.245 12.0004 19.245C8.8704 19.245 6.21537 17.135 5.2654 14.29L1.27539 17.385C3.25539 21.31 7.3104 24.0001 12.0004 24.0001Z" fill="#34A853"/></svg>"""
                                ),
                                cls="w-6 h-6",
                            ),
                            fh.Div(
                                "Continue with Google",
                                cls="flex grow justify-center items-center",
                            ),
                            cls="flex justify-between items-center gap-4",
                        ),
                        cls=f"w-full {click_neutral_button} p-3 {rounded} {shadow}",
                    ),
                    href=google_client.login_link(redir_url(req, "/redirect-google")),
                    cls="w-full",
                ),
                fh.Div(
                    fh.Div(cls=f"flex-grow border-t border-{text_color}"),
                    fh.Span("or", cls=f"flex-shrink px-4 text-{text_color}"),
                    fh.Div(cls=f"flex-grow border-t border-{text_color}"),
                    cls="w-full relative flex justify-center items-center",
                ),
                fh.Form(
                    fh.Input(
                        id="email",
                        name="email",
                        type="email",
                        placeholder="Email",
                        required=True,
                        cls=f"w-full {input_cls}",
                    ),
                    fh.Input(
                        id="password",
                        name="password",
                        type="password",
                        placeholder="Password",
                        required=True,
                        cls=f"w-full {input_cls}",
                    ),
                    fh.Button(
                        fh.P(
                            "Sign Up",
                            id="signup-button-text",
                            cls=f"hide-when-loading text-{text_color} hover:text-{text_button_hover_color}",
                        ),
                        spinner(
                            id="signup-loader",
                            cls=f"w-6 h-6 text-{text_color} hover:text-{text_button_hover_color}",
                        ),
                        id="signup-button",
                        type="submit",
                        cls=f"w-full {click_button} p-3 {rounded} {shadow}",
                    ),
                    hx_post="/auth/signup",
                    hx_target="this",
                    hx_swap="none",
                    hx_indicator="#signup-button-text, #signup-loader",
                    hx_disabled_elt="#email, #password, #signup-button",
                    cls="w-full",
                ),
                cls=f"w-full md:w-1/3 {input_cls} p-8 flex flex-col justify-center items-center gap-4",
            ),
            cls=page_ctnt,
        )

    def login_content(req):
        return fh.Main(
            fh.Div(
                fh.H1(
                    "Log In",
                    cls=f"{title_text} text-{text_color} text-center",
                ),
                fh.P(
                    fh.Span("(No account? "),
                    fh.A(
                        "Sign Up",
                        href="/signup",
                        cls=f"text-{click_color} hover:text-{click_hover_color}",
                    ),
                    fh.Span(")"),
                    cls=f"text-{text_color} text-center",
                ),
                fh.A(
                    fh.Button(
                        fh.Div(
                            fh.Svg(
                                fh.NotStr(
                                    si_github.svg,
                                ),
                                cls="w-6 h-6",
                            ),
                            fh.Div(
                                "Continue with GitHub",
                                cls="flex grow justify-center items-center",
                            ),
                            cls="flex justify-between items-center gap-4",
                        ),
                        cls=f"w-full {click_neutral_button} p-3 {rounded} {shadow}",
                    ),
                    href=github_client.login_link(redir_url(req, "/redirect-github")),
                    cls="w-full",
                ),
                fh.A(
                    fh.Button(
                        fh.Div(
                            fh.Svg(
                                fh.NotStr(
                                    """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M12.0003 4.75C13.7703 4.75 15.3553 5.36002 16.6053 6.54998L20.0303 3.125C17.9502 1.19 15.2353 0 12.0003 0C7.31028 0 3.25527 2.69 1.28027 6.60998L5.27028 9.70498C6.21525 6.86002 8.87028 4.75 12.0003 4.75Z" fill="#EA4335"/><path d="M23.49 12.275C23.49 11.49 23.415 10.73 23.3 10H12V14.51H18.47C18.18 15.99 17.34 17.25 16.08 18.1L19.945 21.1C22.2 19.01 23.49 15.92 23.49 12.275Z" fill="#4285F4"/><path d="M5.26498 14.2949C5.02498 13.5699 4.88501 12.7999 4.88501 11.9999C4.88501 11.1999 5.01998 10.4299 5.26498 9.7049L1.275 6.60986C0.46 8.22986 0 10.0599 0 11.9999C0 13.9399 0.46 15.7699 1.28 17.3899L5.26498 14.2949Z" fill="#FBBC05"/><path d="M12.0004 24.0001C15.2404 24.0001 17.9654 22.935 19.9454 21.095L16.0804 18.095C15.0054 18.82 13.6204 19.245 12.0004 19.245C8.8704 19.245 6.21537 17.135 5.2654 14.29L1.27539 17.385C3.25539 21.31 7.3104 24.0001 12.0004 24.0001Z" fill="#34A853"/></svg>"""
                                ),
                                cls="w-6 h-6",
                            ),
                            fh.Div(
                                "Continue with Google",
                                cls="flex grow justify-center items-center",
                            ),
                            cls="flex justify-between items-center gap-4",
                        ),
                        cls=f"w-full {click_neutral_button} p-3 {rounded} {shadow}",
                    ),
                    href=google_client.login_link(redir_url(req, "/redirect-google")),
                    cls="w-full",
                ),
                fh.Div(
                    fh.Div(cls=f"flex-grow border-t border-{text_color}"),
                    fh.Span("or", cls=f"flex-shrink mx-4 text-{text_color}"),
                    fh.Div(cls=f"flex-grow border-t border-{text_color}"),
                    cls="w-full relative flex justify-center items-center",
                ),
                fh.Form(
                    fh.Input(
                        id="email",
                        name="email",
                        type="email",
                        placeholder="Email",
                        required=True,
                        cls=f"w-full {input_cls}",
                    ),
                    fh.Input(
                        id="password",
                        name="password",
                        type="password",
                        placeholder="Password",
                        required=True,
                        cls=f"w-full {input_cls}",
                    ),
                    fh.Button(
                        fh.P(
                            "Log In",
                            id="login-button-text",
                            cls=f"hide-when-loading text-{text_color} hover:text-{text_button_hover_color}",
                        ),
                        spinner(
                            id="login-loader",
                            cls=f"w-6 h-6 text-{text_color} hover:text-{text_button_hover_color}",
                        ),
                        id="login-button",
                        type="submit",
                        cls=f"w-full {click_button} p-3 {rounded} {shadow}",
                    ),
                    hx_post="/auth/login",
                    hx_target="this",
                    hx_swap="none",
                    hx_indicator="#login-button-text, #login-loader",
                    hx_disabled_elt="#email, #password, #login-button",
                    cls="w-full",
                ),
                fh.Div(
                    fh.A(
                        "Forgot Password?",
                        href="/forgot-password",
                        cls=f"text-{click_color} hover:text-{click_hover_color}",
                    ),
                    cls="w-full",
                ),
                cls=f"w-full md:w-1/3 {input_cls} p-8 flex flex-col justify-center items-center gap-4",
            ),
            cls=page_ctnt,
        )

    def forgot_password_content():
        return fh.Main(
            fh.Form(
                fh.Div(
                    fh.A(
                        "←",
                        href="/login",
                        cls=f"text-{click_color} hover:text-{click_hover_color}",
                    ),
                    fh.H1("Forgot Password?", cls=f"text-{text_color}"),
                    cls=f"w-full {title_text} flex justify-center items-center gap-4",
                ),
                fh.P(
                    "Enter your email below to receive a password reset link.",
                    cls=f"text-{text_color} text-center",
                ),
                fh.Input(
                    id="email",
                    type="email",
                    name="email",
                    placeholder="Email",
                    required=True,
                    cls=f"w-full {input_cls}",
                ),
                fh.Button(
                    fh.P(
                        "Send Reset Link",
                        id="forgot-password-button-text",
                        cls=f"hide-when-loading text-{text_color} hover:text-{text_button_hover_color}",
                    ),
                    spinner(
                        id="forgot-password-loader",
                        cls=f"w-6 h-6 text-{text_color} hover:text-{text_button_hover_color}",
                    ),
                    id="forgot-password-button",
                    type="submit",
                    cls=f"w-full {click_button} p-3 {rounded} {shadow}",
                ),
                hx_post="/auth/forgot-password",
                hx_target="this",
                hx_swap="none",
                hx_indicator="#forgot-password-button-text, #forgot-password-loader",
                hx_disabled_elt="#email, #forgot-password-button",
                cls=f"w-full md:w-1/3 {input_cls} p-8 flex flex-col justify-center items-center gap-8",
            ),
            cls=page_ctnt,
        )

    def reset_password_content(token: str | None = None):
        return fh.Main(
            fh.Form(
                fh.Div(
                    fh.A(
                        "←",
                        href="/login",
                        cls=f"text-{click_color} hover:text-{click_hover_color}",
                    ),
                    fh.H1(
                        "Reset Password",
                        cls=f"text-{text_color}",
                    ),
                    cls=f"w-full {title_text} flex justify-center items-center gap-4",
                ),
                fh.P(
                    "Enter your new password below.",
                    cls=f"text-{text_color} text-center",
                ),
                fh.Input(
                    id="password",
                    name="password",
                    placeholder="New Password",
                    type="password",
                    required=True,
                    cls=f"w-full {input_cls}",
                ),
                fh.Input(
                    id="confirm_password",
                    name="confirm_password",
                    placeholder="Confirm Password",
                    type="password",
                    required=True,
                    cls=f"w-full {input_cls}",
                ),
                fh.Input(
                    type="hidden",
                    name="token",
                    value=token,
                )
                if token
                else "",
                fh.Button(
                    fh.P(
                        "Reset Password",
                        id="reset-password-button-text",
                        cls=f"hide-when-loading text-{text_color} hover:text-{text_button_hover_color}",
                    ),
                    spinner(
                        id="reset-password-loader",
                        cls=f"w-6 h-6 text-{text_color} hover:text-{text_button_hover_color}",
                    ),
                    id="reset-password-button",
                    type="submit",
                    cls=f"w-full {click_button} p-3 {rounded} {shadow}",
                ),
                hx_post="/auth/reset-password",
                hx_target="this",
                hx_swap="none",
                hx_indicator="#reset-password-button-text, #reset-password-loader",
                hx_disabled_elt="#password, #confirm_password, #reset-password-button",
                cls=f"w-full md:w-1/3 {input_cls} p-8 flex flex-col justify-center items-center gap-8",
            ),
            cls=page_ctnt,
        )

    def settings_content(session):
        max_text_length_sm = 7
        max_text_length_md = 12
        max_text_length_lg = 17

        curr_user = get_curr_user(session)
        if not curr_user:
            return fh.Main(
                fh.P(
                    "You must be logged in to view your settings.",
                    cls=f"{large_text} text-{text_color} text-center",
                ),
                cls=page_ctnt,
            )
        return fh.Main(
            fh.Div(
                fh.Div(
                    fh.Img(
                        src=curr_user.profile_img,
                        cls=f"w-20 h-20 object-cover rounded-full {shadow}",
                    ),
                    fh.Button(
                        fh.P(
                            "Edit",
                            id="edit-button-text",
                            cls=f"hide-when-loading text-{text_color} hover:text-{text_button_hover_color}",
                        ),
                        spinner(
                            id="edit-loader",
                            cls=f"w-6 h-6 text-{text_color} hover:text-{text_button_hover_color}",
                        ),
                        hx_get="/user/settings/edit",
                        hx_target="#settings",
                        hx_swap="outerHTML",
                        hx_indicator="#edit-button-text, #edit-loader",
                        hx_disabled_elt="#edit-button",
                        cls=f"max-w-28 md:max-w-40 flex grow justify-center items-center {click_button} {rounded} {shadow} p-3",
                    ),
                    cls="w-full flex justify-between items-center gap-8",
                ),
                fh.Div(
                    fh.P("Email:", cls=f"text-{text_color}"),
                    fh.P(
                        curr_user.email
                        if len(curr_user.email) <= max_text_length_lg
                        else curr_user.email[:max_text_length_lg] + "...",
                        cls=f"text-{text_color} hidden lg:block",
                    ),
                    fh.P(
                        curr_user.email
                        if len(curr_user.email) <= max_text_length_md
                        else curr_user.email[:max_text_length_md] + "...",
                        cls=f"text-{text_color} hidden md:block lg:hidden",
                    ),
                    fh.P(
                        curr_user.email
                        if len(curr_user.email) <= max_text_length_sm
                        else curr_user.email[:max_text_length_sm] + "...",
                        cls=f"text-{text_color} block md:hidden",
                    ),
                    cls="w-full flex justify-between items-center gap-8",
                ),
                fh.Div(
                    fh.P("Username:", cls=f"text-{text_color}"),
                    fh.P(
                        curr_user.username
                        if len(curr_user.username) <= max_text_length_lg
                        else curr_user.username[:max_text_length_lg] + "...",
                        cls=f"text-{text_color} hidden lg:block",
                    ),
                    fh.P(
                        curr_user.username
                        if len(curr_user.username) <= max_text_length_md
                        else curr_user.username[:max_text_length_md] + "...",
                        cls=f"text-{text_color} hidden md:block lg:hidden",
                    ),
                    fh.P(
                        curr_user.username
                        if len(curr_user.username) <= max_text_length_sm
                        else curr_user.username[:max_text_length_sm] + "...",
                        cls=f"text-{text_color} block md:hidden",
                    ),
                    cls="w-full flex justify-between items-center gap-8",
                ),
                fh.Div(
                    fh.P("Password:", cls=f"text-{text_color}"),
                    fh.P("********", cls=f"text-{text_color}"),
                    cls="w-full flex justify-between items-center gap-8",
                )
                if curr_user.login_type == "email"
                else None,
                delete_account_button(),
                id="settings",
                cls=f"w-full md:w-1/3 {input_cls} p-8 flex flex-col justify-center items-center gap-8",
            ),
            cls=page_ctnt,
        )

    # helper fns
    def validate_image_base64(image_base64: str) -> dict[str, str]:
        max_file_size = 10  # MB
        max_img_dim = (4096, 4096)

        # Verify MIME type and magic #
        img = Image.open(io.BytesIO(base64.b64decode(image_base64)))
        try:
            img.verify()
        except Exception as e:
            return {"error": e}

        # Limit img size
        if len(image_base64) > max_file_size * 1024 * 1024:
            return {"error": f"File size exceeds {max_file_size}MB limit."}
        if img.size[0] > max_img_dim[0] or img.size[1] > max_img_dim[1]:
            return {
                "error": f"Image dimensions exceed {max_img_dim[0]}x{max_img_dim[1]} pixels limit."
            }

        # Run antivirus
        # write image_base64 to tmp file
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file.write(base64.b64decode(image_base64))
            tmp_file_path = tmp_file.name

        try:
            result = subprocess.run(  # noqa: S603
                ["python", "main.py", str(tmp_file_path)],  # noqa: S607
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=PARENT_PATH / "Python-Antivirus"
                if modal.is_local()
                else "/root/Python-Antivirus",
            )
            scan_result = result.stdout.strip().lower()
            if scan_result == "infected":
                return {"error": "Potential threat detected."}
        except Exception as e:
            return {"error": f"Error during antivirus scan: {e}"}

        return {"success": image_base64}

    def validate_image_file(
        image_file: fh.UploadFile | None,
    ) -> dict[str, str]:
        if image_file is not None:
            valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff"}
            file_extension = Path(image_file.filename).suffix.lower()
            if file_extension not in valid_extensions:
                return {"error": "Invalid file type. Please upload an image."}
            image_file.file.seek(0)  # reset pointer in case of multiple uploads
            img_bytes = image_file.file.read()
            image_base64 = base64.b64encode(img_bytes).decode("utf-8")
            return validate_image_base64(image_base64)
        return {"error": "No image uploaded"}

    def send_password_reset_email(email, reset_link):
        token_expiry = 24  # hours

        # Email configuration
        sender_email = os.getenv("EMAIL_SENDER")
        smtp_server = os.getenv("SMTP_SERVER")
        smtp_port = int(os.getenv("SMTP_PORT"))
        smtp_username = os.getenv("SMTP_USERNAME")
        smtp_password = os.getenv("SMTP_PASSWORD")

        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = "Password Reset Request"
        message["From"] = sender_email
        message["To"] = email

        # Create plain text version of email
        text = f"""
        Password Reset Request

        You requested a password reset for your account. Please click the link below to reset your password:

        {reset_link}

        If you did not request this password reset, please ignore this email.

        This link will expire in {token_expiry} hours.
        """

        # Create HTML version of email
        html = f"""
        <html>
          <head></head>
          <body>
            <h2>Password Reset Request</h2>
            <p>You requested a password reset for your account. Please click the link below to reset your password:</p>
            <p><a href="{reset_link}">Reset Password</a></p>
            <p>If you did not request this password reset, please ignore this email.</p>
            <p>This link will expire in {token_expiry} hours.</p>
          </body>
        </html>
        """

        # Attach both versions to the message
        part1 = MIMEText(text, "plain")
        part2 = MIMEText(html, "html")
        message.attach(part1)
        message.attach(part2)

        try:
            # Create secure connection with server and send email
            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                if smtp_username and smtp_password:
                    server.login(smtp_username, smtp_password)
                server.sendmail(sender_email, email, message.as_string())
                return True
        except Exception as e:
            print(f"Error sending email: {str(e)}")
            return False

    # pages
    @f_app.get("/")
    def home(
        session,
    ):
        return (
            fh.Title(APP_NAME),
            fh.Div(
                toast_container(),
                nav(session),
                home_content(),
                cls=main_page,
            ),
        )

    @f_app.get("/matches")
    def matches(session):
        return (
            fh.Title(f"{APP_NAME} | matches"),
            fh.Div(
                toast_container(),
                nav(session, "matches"),
                matches_content(session),
                cls=main_page,
            ),
        )

    @f_app.get("/feed")
    def feed(session):
        return (
            fh.Title(f"{APP_NAME} | feed"),
            fh.Div(
                toast_container(),
                nav(session, "feed"),
                feed_content(session),
                cls=main_page,
            ),
        )

    @f_app.get("/signup")
    def signup_page(req, session):
        return (
            fh.Title(f"{APP_NAME} | sign up"),
            fh.Div(
                toast_container(),
                nav(session, show_auth=False),
                signup_content(req),
                cls=main_page,
            ),
        )

    @f_app.get("/login")
    def login_page(req, session):
        return (
            fh.Title(f"{APP_NAME} | log in"),
            fh.Div(
                toast_container(),
                nav(session, show_auth=False),
                login_content(req),
                cls=main_page,
            ),
        )

    @f_app.get("/forgot-password")
    def forgot_password_page(session):
        return (
            fh.Title(f"{APP_NAME} | forgot password"),
            fh.Div(
                toast_container(),
                nav(session, show_auth=False),
                forgot_password_content(),
                cls=main_page,
            ),
        )

    @f_app.get("/reset-password")
    def reset_password_page(req, session):
        token = req.query_params.get("token")
        return (
            fh.Title(f"{APP_NAME} | reset password"),
            fh.Div(
                toast_container(),
                nav(session, show_auth=False),
                reset_password_content(token),
                cls=main_page,
            ),
        )

    @f_app.get("/settings")
    def settings_page(session):
        return (
            fh.Title(f"{APP_NAME} | settings"),
            fh.Div(
                toast_container(),
                nav(session, "settings", True),
                settings_content(session),
                cls=main_page,
            ),
        )

    # routes
    ## set form inputs in session state
    @f_app.post("/set-graduation-year")
    def set_graduation_year(session, graduation_year: int):
        session["graduation_year"] = graduation_year
        return None

    @f_app.post("/set-major")
    def set_major(session, major: str):
        session["major"] = major
        return None

    @f_app.post("/set-minor")
    def set_minor(session, minor: str):
        session["minor"] = minor
        return None

    @f_app.post("/set-interest")
    def set_interest(session, interest: str):
        if not session["interests"]:
            session["interests"] = json.dumps([interest])
        lst_interests = json.loads(session["interests"])
        if interest not in lst_interests:
            lst_interests.append(interest)
        session["interests"] = json.dumps(lst_interests)
        return None

    @f_app.post("/set-trait")
    def set_trait(session, trait: str):
        if not session["traits"]:
            session["traits"] = json.dumps([trait])
        lst_traits = json.loads(session["traits"])
        if trait not in lst_traits:
            lst_traits.append(trait)
        session["traits"] = json.dumps(lst_traits)
        return None

    @f_app.post("/set-schedule")
    def set_schedule(session, schedule_img_file: fh.UploadFile):
        res = validate_image_file(schedule_img_file)
        if "error" in res.keys():
            return (
                fh.Div(
                    id="schedule-img-preview",
                ),
                schedule_img_container(),
                toast_container(message=res["error"], type="error", hidden=False),
            )

        schedule_img = f"data:image/png;base64,{res['success']}"
        is_valid_schedule, schedule_text = (
            get_schedule_text.local(schedule_img)
            if modal.is_local()
            else get_schedule_text.remote(schedule_img)
        )
        if not is_valid_schedule:
            return (
                fh.Div(
                    id="schedule-img-preview",
                ),
                schedule_img_container(),
                toast_container(
                    message="Invalid schedule image.", type="error", hidden=False
                ),
            )

        with get_db_session() as db_session:
            schedule = Schedule(img=schedule_img, text=schedule_text)
            db_session.add(schedule)
            db_session.commit()
            db_session.refresh(schedule)
            session["schedule_id"] = schedule.id
            return (
                fh.Img(
                    src=schedule_img,
                    id="schedule-img-preview",
                    cls="w-60 h-auto md:w-96 md:h-auto object-cover",
                ),
            )

    @f_app.post("/set-bio")
    def set_bio(session, bio: str):
        session["bio"] = bio
        return None

    ## find matches
    @f_app.post("/find-matches")
    def find_matches(session):
        if not session["graduation_year"]:
            return toast_container(
                message="Please select a graduation year.", type="error", hidden=False
            )
        if not session["major"]:
            return toast_container(
                message="Please select a major.", type="error", hidden=False
            )
        if not json.loads(session["interests"]):
            return toast_container(
                message="Please select at least one interest.",
                type="error",
                hidden=False,
            )
        if not json.loads(session["traits"]):
            return toast_container(
                message="Please select at least one trait.", type="error", hidden=False
            )
        if not session["schedule_id"]:
            return toast_container(
                message="Please upload an image of your schedule.",
                type="error",
                hidden=False,
            )
        if not session["bio"]:
            return toast_container(
                message="Please write a bio.", type="error", hidden=False
            )
        if not session["waiting_for_match"]:
            session["waiting_for_match"] = True

        curr_user = get_curr_user(session)
        if not curr_user:
            return fh.Redirect("/signup")

        with get_db_session() as db_session:
            curr_user = db_session.merge(curr_user)
            curr_user.graduation_year = session["graduation_year"]
            curr_user.major = session["major"]
            curr_user.minor = session["minor"]
            curr_user.interests = json.loads(session["interests"])
            curr_user.personality_traits = json.loads(session["traits"])
            curr_user.schedule = db_session.exec(
                select(Schedule).where(Schedule.id == session["schedule_id"])
            ).first()
            curr_user.bio = session["bio"]
            curr_user.waiting_for_match = session["waiting_for_match"]
            db_session.commit()
            db_session.refresh(curr_user)

        session["graduation_year"] = None
        session["major"] = None
        session["minor"] = None
        session["interests"] = None
        session["traits"] = None
        session["schedule_id"] = None
        session["bio"] = None
        session["waiting_for_match"] = None

        return fh.Redirect("/matches")

    ## feed
    def on_connect(ws, send):
        feed_users[id(ws)] = send

    def on_disconnect(ws):
        feed_users.pop(id(ws), None)

    @f_app.ws("/ws", conn=on_connect, disconn=on_disconnect)
    async def ws(session, msg: str, send):
        await send(feed_input())
        if not msg.strip():
            return

        curr_user = get_curr_user(session)
        with get_db_session() as db_session:
            msg = FeedMessage(message=msg, user=curr_user)
            db_session.add(msg)
            db_session.commit()
            db_session.refresh(msg)

        for u in feed_users.values():
            await u(feed_msgs())

    ## overlay
    def overlay(session):
        max_username_length = 17
        curr_user = get_curr_user(session)
        if not curr_user:
            return fh.Redirect("/login")

        return fh.Div(
            fh.Div(
                fh.Img(
                    src=curr_user.profile_img,
                    cls=f"w-12 h-12 object-cover hover:{img_hover} rounded-full {shadow}",
                ),
                fh.P(
                    curr_user.username
                    if len(curr_user.username) <= max_username_length
                    else curr_user.username[:max_username_length] + "...",
                    cls=f"{medium_text} text-{text_color} hover:text-{text_hover_color} hidden md:block",
                ),
                cls=f"flex justify-center items-center gap-4 cursor-pointer hover:{img_hover} hover:text-{text_hover_color}",
                onclick="document.getElementById('overlay-menu').classList.toggle('hidden')",
            ),
            fh.Div(
                fh.A(
                    fh.Button(
                        "Feed",
                        cls=f"w-full {click_neutral_button} p-3 {rounded} {shadow}",
                    ),
                    href="/feed",
                    cls="w-full",
                ),
                fh.A(
                    fh.Button(
                        "Matches",
                        cls=f"w-full {click_neutral_button} p-3 {rounded} {shadow}",
                    ),
                    href="/matches",
                    cls="w-full",
                ),
                fh.A(
                    fh.Button(
                        "Settings",
                        cls=f"w-full {click_neutral_button} p-3 {rounded} {shadow}",
                    ),
                    href="/settings",
                    cls="w-full",
                ),
                fh.Button(
                    fh.P(
                        "Log out",
                        id="logout-button-text",
                        cls=f"hide-when-loading text-{text_color} hover:text-{text_button_hover_color}",
                    ),
                    spinner(
                        id="logout-loader",
                        cls=f"w-6 h-6 text-{text_color} hover:text-{text_button_hover_color}",
                    ),
                    cls=f"w-full {click_button} {rounded} {shadow} p-3",
                    hx_get="/auth/logout",
                    hx_indicator="#logout-button-text, #logout-loader",
                    hx_disabled_elt="#logout-button",
                ),
                id="overlay-menu",
                cls=f"absolute top-16 right-0 min-w-40 z-10 {input_cls} p-2 flex flex-col justify-center items-center gap-2 hidden",
            ),
            id="overlay",
            cls="relative",
        )

    ## auth
    @f_app.get("/auth/logout")
    def logout(session):
        if session["user_uuid"]:
            del session["user_uuid"]
        return fh.Redirect("/")

    @f_app.post("/auth/login")
    def email_login(session, email: str, password: str):
        with get_db_session() as db_session:
            query = select(User).where(User.email == email)
            db_user = db_session.exec(query).first()
            if not db_user:
                return fh.Redirect("/signup")
            else:
                if not db_user.hashed_password:
                    return toast_container(
                        message="This account uses a different login method.",
                        type="error",
                        hidden=False,
                    )
                if not pbkdf2_sha256.verify(password, db_user.hashed_password):
                    return toast_container(
                        message="Incorrect credentials", type="error", hidden=False
                    )
                else:
                    session["user_uuid"] = db_user.uuid
                    curr_user = get_curr_user(session)
                    if session["waiting_for_match"]:
                        with get_db_session() as db_session:
                            curr_user = db_session.merge(curr_user)
                            curr_user.graduation_year = session["graduation_year"]
                            curr_user.major = session["major"]
                            curr_user.minor = session["minor"]
                            curr_user.interests = json.loads(session["interests"])
                            curr_user.personality_traits = json.loads(session["traits"])
                            curr_user.schedule = db_session.exec(
                                select(Schedule).where(
                                    Schedule.id == session["schedule_id"]
                                )
                            ).first()
                            curr_user.bio = session["bio"]
                            curr_user.waiting_for_match = session["waiting_for_match"]
                            db_session.commit()
                            db_session.refresh(curr_user)
                        session["graduation_year"] = None
                        session["major"] = None
                        session["minor"] = None
                        session["interests"] = None
                        session["traits"] = None
                        session["schedule_id"] = None
                        session["bio"] = None
                        session["waiting_for_match"] = None
                    return fh.Redirect("/matches")

    @f_app.post("/auth/signup")
    def email_signup(session, email: str, password: str):
        with get_db_session() as db_session:
            query = select(User).where(User.email == email)
            db_user = db_session.exec(query).first()
            if db_user:
                return fh.Redirect("/login")
            else:
                extra_data = {
                    "hashed_password": pbkdf2_sha256.hash(password),
                }
                db_user = User.model_validate(
                    {
                        "login_type": "email",
                        "profile_img": f"data:image/svg+xml;base64,{base64.b64encode(f'<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\" viewBox=\"0 0 100 100\"><circle cx=\"50\" cy=\"50\" r=\"50\" fill=\"{tailwind_to_hex[click_color]}\"/><text x=\"50\" y=\"60\" font-size=\"40\" text-anchor=\"middle\" fill=\"{tailwind_to_hex[text_color]}\" font-family=\"{font_hex}\">{email[0].upper()}</text></svg>'.encode()).decode()}",
                        "email": email,
                        "username": email,
                    },
                    update=extra_data,
                )
                db_session.add(db_user)
                db_session.commit()
                db_session.refresh(db_user)
                session["user_uuid"] = db_user.uuid
                curr_user = get_curr_user(session)
                if session["waiting_for_match"]:
                    with get_db_session() as db_session:
                        curr_user = db_session.merge(curr_user)
                        curr_user.graduation_year = session["graduation_year"]
                        curr_user.major = session["major"]
                        curr_user.minor = session["minor"]
                        curr_user.interests = json.loads(session["interests"])
                        curr_user.personality_traits = json.loads(session["traits"])
                        curr_user.schedule = db_session.exec(
                            select(Schedule).where(
                                Schedule.id == session["schedule_id"]
                            )
                        ).first()
                        curr_user.bio = session["bio"]
                        curr_user.waiting_for_match = session["waiting_for_match"]
                        db_session.commit()
                        db_session.refresh(curr_user)
                    session["graduation_year"] = None
                    session["major"] = None
                    session["minor"] = None
                    session["interests"] = None
                    session["traits"] = None
                    session["schedule_id"] = None
                    session["bio"] = None
                    session["waiting_for_match"] = None
                return fh.Redirect("/matches")

    @f_app.post("/auth/forgot-password")
    def forgot_password(session, email: str):
        token_expiry = 24  # hours

        with get_db_session() as db_session:
            query = select(User).where(User.email == email)
            db_user = db_session.exec(query).first()
            if not db_user:
                return fh.Redirect("/login")
            if db_user.login_type != "email":
                return toast_container(
                    message="This account uses a different login method.",
                    type="error",
                    hidden=False,
                )

            reset_token = str(uuid.uuid4())
            with get_db_session() as db_session:
                db_user.reset_token = reset_token
                db_user.reset_token_expiry = datetime.now() + timedelta(
                    hours=token_expiry
                )
                db_session.add(db_user)
                db_session.commit()
                db_session.refresh(db_user)
            reset_link = f"{os.getenv('DOMAIN')}/reset-password?token={reset_token}"
            send_password_reset_email(email, reset_link)

            return fh.Redirect("/login")

    @f_app.post("/auth/reset-password")
    def reset_password(session, password: str, confirm_password: str, token: str):
        if password != confirm_password:
            return toast_container(
                message="Passwords do not match", type="error", hidden=False
            )
        if not token:
            return fh.Redirect("/login")

        with get_db_session() as db_session:
            query = select(User).where(User.reset_token == token)
            db_user = db_session.exec(query).first()
            if not db_user:
                return fh.Redirect("/login")
            if db_user.reset_token_expiry < datetime.now():
                return fh.Redirect("/login")

            db_user.hashed_password = pbkdf2_sha256.hash(password)
            db_user.reset_token = None
            db_user.reset_token_expiry = None
            db_session.add(db_user)
            db_session.commit()
            db_session.refresh(db_user)
            return fh.Redirect("/login")

    @f_app.get("/redirect-github")
    def redirect_github(
        request, session, code: str | None = None, error: str | None = None
    ):
        if not code or error:
            return fh.Redirect("/login")

        redir = redir_url(request, "/redirect-github")
        user_info = github_client.retr_info(code, redir)
        email = user_info.get("email", "")
        username = user_info.get("login", "")

        with get_db_session() as db_session:
            query = select(User).where(User.email == email)
            db_user = db_session.exec(query).first()
            if not db_user:
                db_user = User.model_validate(
                    {
                        "login_type": "github",
                        "profile_img": f"data:image/svg+xml;base64,{base64.b64encode(f'<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\" viewBox=\"0 0 100 100\"><circle cx=\"50\" cy=\"50\" r=\"50\" fill=\"{tailwind_to_hex[click_color]}\"/><text x=\"50\" y=\"60\" font-size=\"40\" text-anchor=\"middle\" fill=\"{tailwind_to_hex[text_color]}\" font-family=\"{font_hex}\">{email[0].upper() if email else username[0].upper()}</text></svg>'.encode()).decode()}",
                        "email": email,
                        "username": username,
                    }
                )
                db_session.add(db_user)
                db_session.commit()
                db_session.refresh(db_user)

            session["user_uuid"] = db_user.uuid
            curr_user = get_curr_user(session)
            if session["waiting_for_match"]:
                with get_db_session() as db_session:
                    curr_user = db_session.merge(curr_user)
                    curr_user.graduation_year = session["graduation_year"]
                    curr_user.major = session["major"]
                    curr_user.minor = session["minor"]
                    curr_user.interests = json.loads(session["interests"])
                    curr_user.personality_traits = json.loads(session["traits"])
                    curr_user.schedule = db_session.exec(
                        select(Schedule).where(Schedule.id == session["schedule_id"])
                    ).first()
                    curr_user.bio = session["bio"]
                    curr_user.waiting_for_match = session["waiting_for_match"]
                    db_session.commit()
                    db_session.refresh(curr_user)
                session["graduation_year"] = None
                session["major"] = None
                session["minor"] = None
                session["interests"] = None
                session["traits"] = None
                session["schedule_id"] = None
                session["bio"] = None
                session["waiting_for_match"] = None
            return fh.RedirectResponse("/matches", status_code=303)

    @f_app.get("/redirect-google")
    def redirect_google(
        request, session, code: str | None = None, error: str | None = None
    ):
        if not code or error:
            return fh.Redirect("/login")

        redir = redir_url(request, "/redirect-google")
        user_info = google_client.retr_info(code, redir)
        email = user_info.get("email", "")
        username = email.split("@")[0] if email else ""

        with get_db_session() as db_session:
            query = select(User).where(User.email == email)
            db_user = db_session.exec(query).first()
            if not db_user:
                db_user = User.model_validate(
                    {
                        "login_type": "google",
                        "profile_img": f"data:image/svg+xml;base64,{base64.b64encode(f'<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\" viewBox=\"0 0 100 100\"><circle cx=\"50\" cy=\"50\" r=\"50\" fill=\"{tailwind_to_hex[click_color]}\"/><text x=\"50\" y=\"60\" font-size=\"40\" text-anchor=\"middle\" fill=\"{tailwind_to_hex[text_color]}\" font-family=\"{font_hex}\">{email[0].upper() if email else "U"}</text></svg>'.encode()).decode()}",
                        "email": email,
                        "username": username,
                    }
                )
                db_session.add(db_user)
                db_session.commit()
                db_session.refresh(db_user)

            session["user_uuid"] = db_user.uuid
            curr_user = get_curr_user(session)
            if session["waiting_for_match"]:
                with get_db_session() as db_session:
                    curr_user = db_session.merge(curr_user)
                    curr_user.graduation_year = session["graduation_year"]
                    curr_user.major = session["major"]
                    curr_user.minor = session["minor"]
                    curr_user.interests = json.loads(session["interests"])
                    curr_user.personality_traits = json.loads(session["traits"])
                    curr_user.schedule = db_session.exec(
                        select(Schedule).where(Schedule.id == session["schedule_id"])
                    ).first()
                    curr_user.bio = session["bio"]
                    curr_user.waiting_for_match = session["waiting_for_match"]
                    db_session.commit()
                    db_session.refresh(curr_user)
                session["graduation_year"] = None
                session["major"] = None
                session["minor"] = None
                session["interests"] = None
                session["traits"] = None
                session["schedule_id"] = None
                session["bio"] = None
                session["waiting_for_match"] = None
            return fh.RedirectResponse("/matches", status_code=303)

    ## settings
    @f_app.get("/user/settings/edit")
    def edit_settings(session):
        curr_user = get_curr_user(session)
        return (
            fh.Form(
                fh.Div(
                    fh.Label(
                        fh.Input(
                            id="new-profile-img-upload",
                            name="profile_img_file",
                            type="file",
                            accept="image/*",
                            hx_post="/user/settings/update-preview",
                            hx_target="#profile-img-preview",
                            hx_swap="outerHTML",
                            hx_trigger="change",
                            hx_indicator="#profile-img-preview, #profile-img-loader",
                            hx_disabled_elt="#new-profile-img-upload, #save-button, #delete-account-button",
                            hx_encoding="multipart/form-data",
                            cls="hidden",
                        ),
                        settings_profile_img(curr_user.profile_img),
                        spinner(
                            id="profile-img-loader",
                            cls=f"w-12 h-12 text-{text_color} hover:text-{text_hover_color}",
                        ),
                    ),
                    fh.Button(
                        fh.P(
                            "Save",
                            id="save-button-text",
                            cls=f"hide-when-loading text-{text_color} hover:text-{text_button_hover_color}",
                        ),
                        spinner(
                            id="save-loader",
                            cls=f"w-6 h-6 text-{text_color} hover:text-{text_button_hover_color}",
                        ),
                        id="save-button",
                        type="submit",
                        hx_patch="/user/settings/save",
                        hx_target="this",
                        hx_swap="none",
                        hx_indicator="#save-button-text, #save-loader",
                        hx_disabled_elt="#new-profile-img-upload, #email, #username, #password, #save-button",
                        hx_include="#new-profile-img-upload",
                        hx_encoding="multipart/form-data",
                        cls=f"max-w-28 md:max-w-40 flex grow justify-center items-center {click_button} {rounded} p-3",
                    ),
                    cls="w-full flex justify-between items-center gap-8",
                ),
                fh.Div(
                    fh.P("Email:", cls=f"text-{text_color}"),
                    fh.Input(
                        id="email",
                        value=curr_user.email,
                        name="email",
                        type="email",
                        cls=f"max-w-28 md:max-w-40 flex grow justify-center items-center {input_cls}",
                    ),
                    cls="w-full flex justify-between items-center gap-8",
                ),
                fh.Div(
                    fh.P("Username:", cls=f"text-{text_color}"),
                    fh.Input(
                        id="username",
                        value=curr_user.username,
                        name="username",
                        cls=f"max-w-28 md:max-w-40 flex grow justify-center items-center {input_cls}",
                    ),
                    cls="w-full flex justify-between items-center gap-8",
                ),
                fh.Div(
                    fh.P("Password:", cls=f"text-{text_color}"),
                    fh.Input(
                        id="password",
                        value="",
                        name="password",
                        type="password",
                        cls=f"max-w-28 md:max-w-40 flex grow justify-center items-center {input_cls}",
                    ),
                    cls="w-full flex justify-between items-center gap-8",
                )
                if curr_user.login_type == "email"
                else None,
                delete_account_button(),
                id="settings",
                cls=f"w-full md:w-1/3 {input_cls} p-8 flex flex-col justify-center items-center gap-8",
            ),
        )

    @f_app.post("/user/settings/update-preview")
    def update_preview(
        session,
        profile_img_file: fh.UploadFile,
    ):
        curr_user = get_curr_user(session)
        res = validate_image_file(profile_img_file)
        if "error" in res.keys():
            return (
                (
                    settings_profile_img(curr_user.profile_img),
                    toast_container(message=res["error"], type="error", hidden=False),
                ),
            )
        return settings_profile_img(f"data:image/png;base64,{res['success']}")

    @f_app.patch("/user/settings/save")
    def save_settings(
        session,
        email: str | None = None,
        username: str | None = None,
        password: str | None = None,
        profile_img_file: fh.UploadFile | None = None,
    ):
        curr_user = get_curr_user(session)
        with get_db_session() as db_session:
            if email and email != curr_user.email:
                query = select(User).where(User.email == email)
                db_user = db_session.exec(query).first()
                if db_user:
                    return toast_container(
                        message="Email already exists", type="error", hidden=False
                    )
            curr_user.email = email

            if username and username != curr_user.username:
                query = select(User).where(User.username == username)
                db_user = db_session.exec(query).first()
                if db_user:
                    return toast_container(
                        message="Username already exists", type="error", hidden=False
                    )
            curr_user.username = username

            if curr_user.login_type == "email" and password:
                curr_user.hashed_password = pbkdf2_sha256.hash(password)

            if profile_img_file is not None and not profile_img_file.filename == "":
                res = validate_image_file(profile_img_file)
                if "error" in res.keys():
                    return toast_container(
                        message=res["error"], type="error", hidden=False
                    )
                curr_user.profile_img = f"data:image/png;base64,{res['success']}"

            db_session.add(curr_user)
            db_session.commit()
            db_session.refresh(curr_user)
        return fh.Redirect("/settings")

    @f_app.delete("/user/settings/delete-account")
    def delete_account(session):
        curr_user = get_curr_user(session)
        if curr_user is None:
            return fh.Redirect("/")
        with get_db_session() as db_session:
            db_session.delete(curr_user)
            db_session.commit()
        session.clear()
        return fh.Redirect("/")

    ## misc
    @f_app.get("/{fname:path}.{ext:static}")
    def static_files(fname: str, ext: str):
        static_file_path = PARENT_PATH / f"{fname}.{ext}"
        if static_file_path.exists():
            return fh.FileResponse(static_file_path)

    return f_app


f_app = get_app()

# -----------------------------------------------------------------------------


@app.function(
    image=FE_IMAGE,
    secrets=SECRETS,
    timeout=5 * MINUTES,
    max_containers=1,  # since we're using a session cookie, we need to limit the number of containers
    scaledown_window=15 * MINUTES,
)
@modal.concurrent(max_inputs=1000)
@modal.asgi_app()
def modal_get():
    return f_app


if __name__ == "__main__":
    fh.serve(app="f_app")
