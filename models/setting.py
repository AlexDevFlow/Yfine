from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Setting(SQLModel, table=True):
    __tablename__ = "settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    locale: str = Field(default="en")
    date_format: str = Field(default="dd/mm/yyyy")
    base_currency: Optional[str] = None
    theme: str = Field(default="light")
    hide_net_worth: bool = Field(default=False)
    last_source_id: Optional[int] = Field(default=None)
    mobile_nav_mode: str = Field(default="sidebar")
    ui_scale: str = Field(default="normal")
    hotkeys_enabled: bool = Field(default=True)
    hotkeys_json: str = Field(default="{}")
    nav_layout_json: str = Field(default="[]")
    lan_access: bool = Field(default=False)
    portfolio_prices_enabled: bool = Field(default=False)
    portfolio_prices_prompted: bool = Field(default=False)
    # Movements power UX (JSON blobs, like hotkeys_json/nav_layout_json):
    # saved filter views and quick-add movement templates.
    saved_views_json: str = Field(default="[]")
    movement_templates_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
