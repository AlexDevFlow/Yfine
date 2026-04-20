from datetime import datetime

from sqlmodel import Session

from models.setting import Setting
from schemas.setting import SettingUpdate


def get_settings(session: Session) -> Setting:
    setting = session.get(Setting, 1)
    if not setting:
        setting = Setting(id=1)
        session.add(setting)
        session.commit()
        session.refresh(setting)
    return setting


def update_settings(session: Session, data: SettingUpdate) -> Setting:
    setting = get_settings(session)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(setting, key, value)
    setting.updated_at = datetime.utcnow()
    session.add(setting)
    session.commit()
    session.refresh(setting)

    if "locale" in update_data:
        from i18n import set_locale
        set_locale(update_data["locale"])
    if "date_format" in update_data:
        from i18n import set_date_format
        set_date_format(update_data["date_format"])
    if "theme" in update_data:
        from i18n import set_theme
        set_theme(update_data["theme"])
    if "hide_net_worth" in update_data:
        from i18n import set_hide_net_worth
        set_hide_net_worth(update_data["hide_net_worth"])
    if "last_source_id" in update_data:
        from i18n import set_last_source_id
        set_last_source_id(update_data["last_source_id"])
    if "mobile_nav_mode" in update_data:
        from i18n import set_mobile_nav_mode
        set_mobile_nav_mode(update_data["mobile_nav_mode"])

    # Persist settings to auth config so they work even when the DB is encrypted
    _sync_keys = {"lan_access", "locale"}
    keys_to_sync = _sync_keys & update_data.keys()
    if keys_to_sync:
        from security import get_auth_config, save_auth_config
        config = get_auth_config()
        if config is not None:
            for k in keys_to_sync:
                config[k] = update_data[k]
            save_auth_config(config)

    return setting
