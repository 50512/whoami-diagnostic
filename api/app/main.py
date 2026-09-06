from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
import os
import re

app = FastAPI()
IP_HOSTS = [
    os.environ.get("IPV4_HOST"),
    os.environ.get("IPV6_HOST")
]

CLI_REGEX = re.compile(r"(?i)(curl|wget|python|httpie|aria2)")

def get_plain_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "127.0.0.1").split(",")[0]

@app.middleware("http")
async def enforce_https(request: Request, call_next):
    """
    Solo redirige a https cuando:
    - No es herramienta cli
    - No pertenece a los IP_HOSTS
    """
    user_agent = request.headers.get("user-agent", "")
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "")
    
    is_cli = bool(CLI_REGEX.search(user_agent)) or not user_agent
    response = None
    
    if forwarded_proto == "https":
        response = await call_next(request)

    elif forwarded_proto == "http":
        if is_cli or host in IP_HOSTS:
            response = await call_next(request)
        else:
            secure_url = f"https://{host}{request.url.path}"
            if request.url.query:
                secure_url += f"?{request.url.query}"
            return RedirectResponse(url=secure_url, status_code=301)
    
    return response

@app.get("/")
@app.get("/ip")
async def root_dispatcher(request: Request):
    client_ip = get_plain_ip(request)
    return PlainTextResponse(content=f"{client_ip}\n")
