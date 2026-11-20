"""Cap the verification JSON body before FastAPI decodes the manuscript."""
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class VerificationBodyLimit:
    # A two-megabyte string can expand sixfold through JSON unicode escaping.
    limit = 12_010_000

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/verify" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > self.limit:
                raise HTTPException(413, "Verification request is too large.")
            return message

        headers = dict(scope["headers"])
        length = headers.get(b"content-length", b"")
        if length.isdigit() and (len(length) > 12 or int(length) > self.limit):
            return await JSONResponse({"detail": "Verification request is too large."}, 413)(scope, receive, send)
        return await self.app(scope, bounded_receive, send)
