from typing import Optional

from pydantic import BaseModel


class SettingRead(BaseModel):
    id: int
    locale: str
    date_format: str = "dd/mm/yyyy"
    base_currency: Optional[str] = None
    theme: str = "light"
    hide_net_worth: bool = False
    last_source_id: Optional[int] = None
    mobile_nav_mode: str = "sidebar"
    ui_scale: str = "normal"
    lan_access: bool = False
    portfolio_prices_enabled: bool = False
    portfolio_prices_prompted: bool = False


class SettingUpdate(BaseModel):
    locale: Optional[str] = None
    date_format: Optional[str] = None
    base_currency: Optional[str] = None
    theme: Optional[str] = None
    hide_net_worth: Optional[bool] = None
    last_source_id: Optional[int] = None
    mobile_nav_mode: Optional[str] = None
    ui_scale: Optional[str] = None
    lan_access: Optional[bool] = None
    portfolio_prices_enabled: Optional[bool] = None
    portfolio_prices_prompted: Optional[bool] = None
