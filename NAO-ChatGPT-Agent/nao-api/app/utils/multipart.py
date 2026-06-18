#utils/multipart.py — multipart/form-data parser with no external dependencies.


import re
import io
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FormFile:
    #represents a file received via form data
     
    name: str                  #field name (e.g. "audio", "photo")
    filename: str              #original file name
    content_type: str          #declared MIME type
    data: bytes                #binary content

    @property
    def size(self) -> int:
        return len(self.data)

    def __repr__(self) -> str:
        return f"<FormFile name={self.name!r} filename={self.filename!r} size={self.size}>"


@dataclass
class ParsedForm:
    #result of parsing a multipart/form data body

    fields: dict[str, str]            = field(default_factory=dict)
    files:  dict[str, FormFile]       = field(default_factory=dict)

    def get_file(self, name: str) -> Optional[FormFile]:
        return self.files.get(name)

    def get_field(self, name: str, default: str = "") -> str:
        return self.fields.get(name, default)


class MultipartParseError(ValueError):
    pass


def parse(body: bytes, content_type: str) -> ParsedForm:
    #parses the body and returns a parsedform

    boundary = _extract_boundary(content_type)
    if not boundary:
        raise MultipartParseError(f"Boundary not found in Content-Type: {content_type!r}")

    result = ParsedForm()
    parts = _split_parts(body, boundary.encode())

    for part in parts:
        if not part:
            continue
        headers_raw, _, content = part.partition(b"\r\n\r\n")
        if not headers_raw:
            continue

        headers = _parse_part_headers(headers_raw)
        disposition = headers.get("content-disposition", "")

        part_name = _header_param(disposition, "name")
        filename   = _header_param(disposition, "filename")

        if not part_name:
            continue

        content_mime = headers.get("content-type", "application/octet-stream").strip()

        if filename:
            #file field
            result.files[part_name] = FormFile(
                name=part_name,
                filename=filename,
                content_type=content_mime,
                data=content,
            )
        else:
            #text field
            result.fields[part_name] = content.decode("utf-8", errors="replace")

    return result


#internals                                                          
def _extract_boundary(content_type: str) -> Optional[str]:
    m = re.search(r'boundary=([^\s;]+)', content_type, re.IGNORECASE)
    if m:
        return m.group(1).strip('"').strip("'")
    return None


def _split_parts(body: bytes, boundary: bytes) -> list[bytes]:
    
    delimiter = b"--" + boundary
    parts: list[bytes] = []
    segments = body.split(delimiter)
    for seg in segments[1:]:                     #skip preamble
        if seg in (b"--", b"--\r\n", b"\r\n--"):
            break
        if seg.startswith(b"\r\n"):
            seg = seg[2:]
        if seg.endswith(b"\r\n"):
            seg = seg[:-2]
        parts.append(seg)
    return parts


def _parse_part_headers(raw: bytes) -> dict[str, str]:
    
    headers: dict[str, str] = {}
    for line in raw.split(b"\r\n"):
        if b":" in line:
            k, _, v = line.partition(b":")
            headers[k.strip().lower().decode()] = v.strip().decode("utf-8", errors="replace")
    return headers


def _header_param(header_value: str, param: str) -> str:
    #extracts a parameter from a header such as Content Disposition
    
    pattern = rf'{re.escape(param)}=["\']?([^"\';\r\n]+)["\']?'
    m = re.search(pattern, header_value, re.IGNORECASE)
    return m.group(1).strip() if m else ""
