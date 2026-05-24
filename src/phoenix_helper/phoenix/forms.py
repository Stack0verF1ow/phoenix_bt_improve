from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass(frozen=True, slots=True)
class UploadForm:
    action: str
    fields: dict[str, str]
    title_field: str
    subtitle_field: str
    description_field: str
    file_field: str
    category_field: str
    tags_field: str | None
    tags_fid_field: str | None
    submit_field: str | None


class UploadFormError(ValueError):
    pass


HIDDEN_FIELD_NAMES = {
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__EVENTVALIDATION",
    "__EVENTTARGET",
    "__EVENTARGUMENT",
    "ToolkitScriptManager1_HiddenField",
}


def parse_upload_form(html: str, base_url: str = "") -> UploadForm:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if form is None:
        raise UploadFormError("upload form not found")

    fields: dict[str, str] = {}
    for element in form.find_all(["input", "textarea", "select"]):
        name = element.get("name")
        if not name:
            continue
        tag_name = element.name or ""
        input_type = (element.get("type") or "").lower()
        if tag_name == "textarea":
            value = element.text or ""
        elif tag_name == "select":
            selected = element.find("option", selected=True) or element.find("option")
            value = selected.get("value", "") if selected else ""
        elif input_type in {"checkbox", "radio"}:
            if element.has_attr("checked"):
                value = element.get("value", "on")
            else:
                continue
        elif input_type == "file":
            continue
        else:
            value = element.get("value", "")
        fields[name] = value

    return UploadForm(
        action=form.get("action", ""),
        fields=fields,
        title_field=_find_field(form, "input", "txtName"),
        subtitle_field=_find_field(form, "input", "txtNameExtra"),
        description_field=_find_field(form, "textarea", "txtDescription"),
        file_field=_find_field(form, "input", "fuFile"),
        category_field=_find_field(form, "select", "ddlCategory"),
        tags_field=_find_optional_field(form, "input", "txtTags"),
        submit_field=_find_optional_field(form, "input", "btnUpload"),
    )


def _find_field(form: object, tag: str, id_suffix: str) -> str:
    field = _find_optional_field(form, tag, id_suffix)
    if field is None:
        raise UploadFormError(f"field ending with {id_suffix!r} not found")
    return field


def _find_optional_field(form: object, tag: str, id_suffix: str) -> str | None:
    element = form.find(tag, id=lambda value: isinstance(value, str) and value.endswith(id_suffix))
    if element is None:
        element = form.find(tag, attrs={"name": lambda value: isinstance(value, str) and value.endswith(id_suffix)})
    if element is None:
        return None
    name = element.get("name")
    return str(name) if name else None
