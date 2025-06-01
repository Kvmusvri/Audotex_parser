from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from core.login.parser import login_audatex
import json
import os
from datetime import datetime
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация FastAPI приложения
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Эндпоинт для главной страницы
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Эндпоинт для авторизации и поиска
@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...),
                claim_number: str = Form(default=""), vin_number: str = Form(default="")):
    parser_result = await login_audatex(username, password, claim_number, vin_number)

    if "error" in parser_result:
        logger.error(f"Ошибка парсинга: {parser_result['error']}")
        return templates.TemplateResponse("error.html", {"request": request, "error": parser_result['error']})

    zone_data = parser_result.get("zone_data", [])
    if not zone_data:
        logger.warning("Зоны не найдены для указанного номера дела или VIN")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Зоны не найдены для указанного номера дела или VIN"
        })

    # Формируем folder_name
    folder_name = vin_number if vin_number else claim_number if claim_number else datetime.now().strftime("%Y%m%d_%H%M%S")

    # Формируем record для history_detail.html
    record = {
        "folder": folder_name,
        "vin_value": parser_result.get("vin_value", vin_number or claim_number),
        "zone_data": [
            {
                "title": zone["title"],
                "screenshot_path": zone["screenshot_path"].replace("/static/screenshots", f"/static/screenshots/{folder_name}").replace("\\", "/"),
                "svg_path": zone["svg_path"].replace("/static/svgs", f"/static/svgs/{folder_name}").replace("\\", "/") if zone.get("svg_path") else "",
                "has_pictograms": zone.get("has_pictograms", False),
                "graphics_not_available": zone.get("graphics_not_available", False),
                "details": [
                    {
                        "title": detail["title"],
                        "svg_path": detail["svg_path"].replace("/static/svgs", f"/static/svgs/{folder_name}").replace("\\", "/")
                    } for detail in zone.get("details", [])
                ],
                "pictograms": [
                    {
                        "section_name": pictogram["section_name"],
                        "works": [
                            {
                                "work_name1": work["work_name1"],
                                "work_name2": work["work_name2"],
                                "svg_path": work["svg_path"].replace("/static/svgs", f"/static/svgs/{folder_name}").replace("\\", "/")
                            } for work in pictogram["works"]
                        ]
                    } for pictogram in zone.get("pictograms", [])
                ]
            } for zone in zone_data
        ],
        "main_screenshot_path": parser_result.get("main_screenshot_path", "").replace("/static/screenshots", f"/static/screenshots/{folder_name}").replace("\\", "/"),
        "main_svg_path": parser_result.get("main_svg_path", "").replace("/static/svgs", f"/static/svgs/{folder_name}").replace("\\", "/"),
        "all_svgs_zip": parser_result.get("all_svgs_zip", "").replace("\\", "/"),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    logger.info("Парсинг успешно завершен, отображаем результаты")
    return templates.TemplateResponse("history_detail.html", {
        "request": request,
        "record": record
    })

# Эндпоинт для истории
@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    history_data = []
    data_base_dir = "static/data"

    logger.debug(f"Сканирование директории: {data_base_dir}")
    if not os.path.exists(data_base_dir):
        logger.error(f"Директория {data_base_dir} не существует")
        return templates.TemplateResponse("history.html", {
            "request": request,
            "history": True,
            "history_data": []
        })

    for root, dirs, files in os.walk(data_base_dir):
        json_files = [f for f in files if f.endswith(".json")]
        if not json_files:
            logger.debug(f"JSON-файлы не найдены в {root}")
            continue
        latest_json = max(json_files, key=lambda f: os.path.getctime(os.path.join(root, f)))
        file_path = os.path.join(root, latest_json)
        folder = os.path.relpath(root, data_base_dir).replace(os.sep, "/")
        logger.debug(f"Чтение JSON: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            file_stat = os.stat(file_path)
            history_data.append({
                "folder": folder,
                "vin_value": data.get("vin_value", folder.split("/")[-1]),
                "created": datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
            })
            logger.debug(f"Успешно загружен JSON: {file_path}")
        except Exception as e:
            logger.error(f"Ошибка при чтении {file_path}: {e}")

    logger.info(f"Найдено записей истории: {len(history_data)}")
    return templates.TemplateResponse("history.html", {
        "request": request,
        "history": True,
        "history_data": history_data
    })

# Эндпоинт для данных конкретной папки
@app.get("/history/{folder:path}", response_class=HTMLResponse)
async def history_detail(request: Request, folder: str):
    data_base_dir = "static/data"
    folder_path = os.path.join(data_base_dir, folder)
    logger.debug(f"Загрузка данных для папки: {folder_path}")

    if not os.path.isdir(folder_path):
        logger.error(f"Папка {folder_path} не существует")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Папка не найдена"
        })

    json_files = [f for f in os.listdir(folder_path) if f.endswith(".json")]
    if not json_files:
        logger.error(f"JSON-файлы не найдены в {folder_path}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Данные не найдены"
        })

    latest_json = max(json_files, key=lambda f: os.path.getctime(os.path.join(folder_path, f)))
    file_path = os.path.join(folder_path, latest_json)
    logger.debug(f"Чтение JSON: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        file_stat = os.stat(file_path)
        claim_number = folder.split("/")[0]  # Извлекаем 3076224 из 3076224/LVVDB21B0PD986324
        record = {
            "folder": folder,
            "vin_value": data.get("vin_value", folder.split("/")[-1]),
            "zone_data": [
                {
                    "title": zone["title"],
                    "screenshot_path": zone["screenshot_path"].replace("/static/screenshots", f"/static/screenshots/{claim_number}").replace("\\", "/"),
                    "svg_path": zone["svg_path"].replace("/static/svgs", f"/static/svgs/{claim_number}").replace("\\", "/") if zone.get("svg_path") else "",
                    "has_pictograms": zone.get("has_pictograms", False),
                    "graphics_not_available": zone.get("graphics_not_available", False),
                    "details": [
                        {
                            "title": detail["title"],
                            "svg_path": detail["svg_path"].replace("/static/svgs", f"/static/svgs/{claim_number}").replace("\\", "/")
                        } for detail in zone.get("details", [])
                    ],
                    "pictograms": [
                        {
                            "section_name": pictogram["section_name"],
                            "works": [
                                {
                                    "work_name1": work["work_name1"],
                                    "work_name2": work["work_name2"],
                                    "svg_path": work["svg_path"].replace("/static/svgs", f"/static/svgs/{claim_number}").replace("\\", "/")
                                } for work in pictogram["works"]
                            ]
                        } for pictogram in zone.get("pictograms", [])
                    ]
                } for zone in data.get("zone_data", [])
            ],
            "main_screenshot_path": data.get("main_screenshot_path", "").replace("/static/screenshots", f"/static/screenshots/{claim_number}").replace("\\", "/"),
            "main_svg_path": data.get("main_svg_path", "").replace("/static/svgs", f"/static/svgs/{claim_number}").replace("\\", "/"),
            "all_svgs_zip": data.get("all_svgs_zip", "").replace("\\", "/"),
            "created": datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        }
        logger.debug(f"Успешно загружен JSON: {file_path}")
        return templates.TemplateResponse("history_detail.html", {
            "request": request,
            "record": record
        })
    except Exception as e:
        logger.error(f"Ошибка при чтении {file_path}: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Ошибка загрузки данных: {e}"
        })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)