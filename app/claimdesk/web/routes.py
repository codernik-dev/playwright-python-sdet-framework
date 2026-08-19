"""Server-rendered HTML interface.

Deliberately plain: forms, tables and links, with a small amount of JavaScript for
the asynchronous claim filter. No front-end build step, so the repository stays
Python-only and the container image stays small — while still giving the browser
tests genuinely asynchronous behaviour to wait on.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimdesk.db import get_session
from claimdesk.deps import SESSION_COOKIE_NAME
from claimdesk.domain import ClaimAction, ClaimStatus, Role
from claimdesk.models import ClaimEvent, Payout, Policy, User
from claimdesk.schemas import DESCRIPTION_MAX_LENGTH, DESCRIPTION_MIN_LENGTH
from claimdesk.security import TokenError, create_access_token, decode_access_token, verify_password
from claimdesk.services import (
    ClaimFilters,
    apply_transition,
    create_claim,
    get_visible_claim,
    list_claims,
)

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

PAGE_SIZE = 10


def current_web_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    """Resolve the browser session, returning ``None`` rather than raising.

    The HTML interface redirects an anonymous visitor to the login page; only the
    API returns 401. Same token, different presentation.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TokenError, ValueError, TypeError):
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def _login_redirect(next_path: str) -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={next_path}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/", include_in_schema=False)
def index(user: User | None = Depends(current_web_user)) -> RedirectResponse:
    target = "/dashboard" if user else "/login"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_form(
    request: Request,
    next_url: str = Query(default="/dashboard", alias="next"),
) -> Response:
    return templates.TemplateResponse(request, "login.html", {"next": next_url, "error": None})


@router.post("/login", include_in_schema=False)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_url: str = Form(default="/dashboard", alias="next"),
    session: Session = Depends(get_session),
) -> Response:
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash) or not user.is_active:
        # 200 with the form re-rendered, not a redirect: the browser test can assert
        # the error is visible without chasing a redirect chain.
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next_url, "error": "Invalid email or password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token, expires_in = create_access_token(user.id, user.role)
    # Only allow relative redirects, so ?next= cannot be used as an open redirect.
    destination = (
        next_url if next_url.startswith("/") and not next_url.startswith("//") else "/dashboard"
    )
    response = RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE_NAME, token, httponly=True, samesite="lax", max_age=expires_in, path="/"
    )
    return response


@router.post("/logout", include_in_schema=False)
def logout() -> Response:
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(
    request: Request,
    user: User | None = Depends(current_web_user),
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _login_redirect("/dashboard")

    counts: dict[str, int] = {}
    for claim_status in ClaimStatus:
        _, total = list_claims(
            session,
            actor=user,
            filters=ClaimFilters(status=claim_status, size=1),
        )
        counts[claim_status.value] = total

    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "counts": counts})


def _parse_decimal(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _claims_context(
    request: Request,
    *,
    user: User,
    session: Session,
    status_value: str | None,
    q: str | None,
    sort: str,
    page: int,
) -> dict[str, object]:
    claim_status = ClaimStatus(status_value) if status_value else None
    filters = ClaimFilters(status=claim_status, q=q, sort=sort, page=page, size=PAGE_SIZE)
    items, total = list_claims(session, actor=user, filters=filters)
    return {
        "request": request,
        "user": user,
        "claims": items,
        "total": total,
        "page": page,
        "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        "status_value": status_value or "",
        "q": q or "",
        "sort": sort,
        "statuses": [s.value for s in ClaimStatus],
    }


@router.get("/claims", response_class=HTMLResponse, include_in_schema=False)
def claims_page(
    request: Request,
    status_value: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    sort: str = "-created_at",
    page: int = Query(default=1, ge=1),
    user: User | None = Depends(current_web_user),
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _login_redirect("/claims")
    context = _claims_context(
        request, user=user, session=session, status_value=status_value, q=q, sort=sort, page=page
    )
    return templates.TemplateResponse(request, "claims.html", context)


@router.get("/claims/table", response_class=HTMLResponse, include_in_schema=False)
def claims_table_partial(
    request: Request,
    status_value: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    sort: str = "-created_at",
    page: int = Query(default=1, ge=1),
    user: User | None = Depends(current_web_user),
    session: Session = Depends(get_session),
) -> Response:
    """The table alone, fetched asynchronously when a filter changes."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    context = _claims_context(
        request, user=user, session=session, status_value=status_value, q=q, sort=sort, page=page
    )
    return templates.TemplateResponse(request, "_claims_table.html", context)


@router.get("/claims/new", response_class=HTMLResponse, include_in_schema=False)
def new_claim_form(
    request: Request,
    user: User | None = Depends(current_web_user),
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _login_redirect("/claims/new")
    query = select(Policy).where(Policy.is_active.is_(True)).order_by(Policy.policy_number)
    if user.role == Role.CUSTOMER.value:
        query = query.where(Policy.holder_id == user.id)
    return templates.TemplateResponse(
        request,
        "claim_new.html",
        {
            "user": user,
            "policies": list(session.scalars(query).all()),
            "error": None,
            "today": date.today().isoformat(),
            "min_length": DESCRIPTION_MIN_LENGTH,
            "max_length": DESCRIPTION_MAX_LENGTH,
            "form": {},
        },
    )


@router.post("/claims/new", include_in_schema=False)
def new_claim_submit(
    request: Request,
    policy_id: str = Form(...),
    amount: str = Form(...),
    description: str = Form(...),
    incident_date: str = Form(...),
    user: User | None = Depends(current_web_user),
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _login_redirect("/claims/new")

    def _render_error(message: str) -> Response:
        query = select(Policy).where(Policy.is_active.is_(True)).order_by(Policy.policy_number)
        if user.role == Role.CUSTOMER.value:
            query = query.where(Policy.holder_id == user.id)
        return templates.TemplateResponse(
            request,
            "claim_new.html",
            {
                "user": user,
                "policies": list(session.scalars(query).all()),
                "error": message,
                "today": date.today().isoformat(),
                "min_length": DESCRIPTION_MIN_LENGTH,
                "max_length": DESCRIPTION_MAX_LENGTH,
                "form": {
                    "policy_id": policy_id,
                    "amount": amount,
                    "description": description,
                    "incident_date": incident_date,
                },
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    parsed_amount = _parse_decimal(amount)
    if parsed_amount is None:
        return _render_error("Amount must be a number, for example 1250.00")
    if not DESCRIPTION_MIN_LENGTH <= len(description) <= DESCRIPTION_MAX_LENGTH:
        return _render_error(
            f"Description must be between {DESCRIPTION_MIN_LENGTH} and "
            f"{DESCRIPTION_MAX_LENGTH} characters."
        )
    try:
        parsed_date = date.fromisoformat(incident_date)
    except ValueError:
        return _render_error("Incident date must be a valid date.")
    if parsed_date > date.today():
        return _render_error("Incident date cannot be in the future.")

    try:
        claim = create_claim(
            session,
            actor=user,
            policy_id=uuid.UUID(policy_id),
            amount=parsed_amount,
            description=description,
            incident_date=parsed_date,
        )
    except (ValueError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else "Invalid policy"
        return _render_error(str(detail))

    return RedirectResponse(url=f"/claims/{claim.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/claims/{claim_id}", response_class=HTMLResponse, include_in_schema=False)
def claim_detail(
    request: Request,
    claim_id: uuid.UUID,
    message: str | None = None,
    error: str | None = None,
    user: User | None = Depends(current_web_user),
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _login_redirect(f"/claims/{claim_id}")

    claim = get_visible_claim(session, actor=user, claim_id=claim_id)
    events = list(
        session.scalars(
            select(ClaimEvent)
            .where(ClaimEvent.claim_id == claim.id)
            .order_by(ClaimEvent.occurred_at)
        ).all()
    )
    payout = session.scalar(select(Payout).where(Payout.claim_id == claim.id))

    current = ClaimStatus(claim.status)
    available = [
        action.value
        for action in ClaimAction
        if _action_is_offered(
            action, current=current, user=user, is_owner=claim.claimant_id == user.id
        )
    ]

    return templates.TemplateResponse(
        request,
        "claim_detail.html",
        {
            "user": user,
            "claim": claim,
            "events": events,
            "payout": payout,
            "actions": available,
            "message": message,
            "error": error,
        },
    )


def _action_is_offered(
    action: ClaimAction, *, current: ClaimStatus, user: User, is_owner: bool
) -> bool:
    """Whether to render a button for this action.

    Only the source status and the role are considered — the approval limit is
    deliberately **not** applied here. An adjuster still sees the Approve button on
    an over-limit claim and is refused on submit, which is what UI-CLM-011 asserts.
    Hiding the button would make the rule untestable through the interface and
    would move authorisation into the template, where it does not belong.
    """
    from claimdesk.domain import TRANSITIONS

    rule = TRANSITIONS[action]
    if current is not rule.source:
        return False
    if Role(user.role) not in rule.roles:
        return False
    return not (rule.owner_only and not is_owner)


@router.post("/claims/{claim_id}/action", include_in_schema=False)
def claim_action(
    claim_id: uuid.UUID,
    action: str = Form(...),
    user: User | None = Depends(current_web_user),
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _login_redirect(f"/claims/{claim_id}")

    claim = get_visible_claim(session, actor=user, claim_id=claim_id)
    try:
        apply_transition(session, claim=claim, actor=user, action=ClaimAction(action))
    except HTTPException as exc:
        return RedirectResponse(
            url=f"/claims/{claim_id}?error={exc.detail}", status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(
        url=f"/claims/{claim_id}?message=Claim+updated", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/admin/users", response_class=HTMLResponse, include_in_schema=False)
def admin_users(
    request: Request,
    user: User | None = Depends(current_web_user),
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _login_redirect("/admin/users")
    if user.role != Role.ADMIN.value:
        return templates.TemplateResponse(
            request, "forbidden.html", {"user": user}, status_code=status.HTTP_403_FORBIDDEN
        )
    users = list(session.scalars(select(User).order_by(User.created_at)).all())
    return templates.TemplateResponse(request, "admin_users.html", {"user": user, "users": users})


@router.post("/admin/users/{user_id}/toggle", include_in_schema=False)
def admin_toggle_user(
    user_id: uuid.UUID,
    user: User | None = Depends(current_web_user),
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _login_redirect("/admin/users")
    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrators only")

    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id != user.id:
        target.is_active = not target.is_active
        session.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)
