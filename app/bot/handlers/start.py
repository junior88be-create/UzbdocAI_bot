"""/start, /help, /about, and main-menu navigation."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.main import MainMenuCallback, main_menu_keyboard
from app.bot.utils import editable_message

router = Router(name="start")

_WELCOME = (
    "👋 <b>Document AI Bot</b>'га хуш келибсиз.\n\n"
    "Менга PDF, сканланган ҳужжат ёки расм (JPG/PNG) юборинг - қўлёзма "
    "матнлар ҳам мумкин - мен уни сарлавҳалар, хатбошилар, жадваллар, "
    "рўйхатлар, саналар, исмлар ва ҳужжат рақамларини имкон қадар аниқ "
    "сақлаган ҳолда тузилган DOCX, Excel ёки Markdown файлига айлантираман.\n\n"
    "🎙 Овозли хабар ёки аудио файл юборсангиз, уни ўзбек (кирилл/лотин) "
    "ёки рус тилида саводли матнга айлантириб, сўзловчилар ва вақт "
    "белгилари билан Word файли сифатида қайтараман.\n\n"
    "Пастдаги тугмалардан бирини танланг ёки шунчаки файл/овоз юборинг."
)

_HELP = (
    "<b>Ботдан қандай фойдаланиш керак</b>\n\n"
    "1. PDF ёки расм (JPG/PNG) юборинг - сканланган ёки қўлёзма ҳужжатлар ҳам мумкин.\n"
    "2. Чиқиш форматини танланг: DOCX, Excel, Markdown, барчаси ёки Автоматик.\n"
    "3. Қайта ишланишини кутинг - жараён битта хабарда жонли янгиланиб боради.\n"
    "4. Тайёр файл(лар)ни юклаб олинг.\n\n"
    "<b>Пакетли қайта ишлаш:</b> 📦 Пакетли қайта ишлаш тугмасини босинг ёки /batch "
    "буйруғини юборинг - бир нечта PDF/расмни йиғиб, барчасини биргаликда қайта "
    "ишлаб, битта ZIP файл сифатида олинг.\n\n"
    "<b>Овозни матнга айлантириш:</b> 🎙 Овозли хабар ёки аудио файл юборинг - "
    "мен уни ўзбек (кирилл/лотин) ёки рус тилида грамматик жиҳатдан тўғри "
    "матнга айлантириб, ҳар бир сўзловчини ва у гапирган вақтни (мас. "
    "[00:15] Спикер 1) кўрсатган ҳолда Word (DOCX) файли сифатида "
    "қайтараман. Хира/шовқинли жойлар мазмунга қараб мантиқан тикланади, "
    "лекин айтилмаган маълумот ҳеч қачон қўшилмайди.\n\n"
    "<b>Тарих ва қидирув:</b> 📚 Тарих орқали сўнгги ҳужжатларингизни кўринг, ёки "
    "🔍 Қидирув / <code>/search &lt;матн&gt;</code> орқали олдинги ҳужжатни номи ёки "
    "мазмуни бўйича топинг (тиллар/ёзувлар бўйлаб ишлайди).\n\n"
    "<b>Қўллаб-қувватланадиган тиллар:</b> Ўзбек (лотин), Ўзбек (кирилл), Рус, "
    "Инглиз. Бот ҳужжатнинг асл тилини ҳар доим сақлайди - сўралмагунча "
    "таржима қилмайди.\n\n"
    "<b>Чекловлар:</b> максимал файл ҳажми, бет сони ва пакет ҳажми администратор "
    "томонидан белгиланади.\n\n"
    "<b>Махфийлик эслатмаси:</b> юкланган файллар ва яратилган ҳужжатлар "
    "вақтинчалик сақланади ва белгиланган муддатдан сўнг автоматик ўчирилади - "
    "муддати тугаган ҳужжатнинг мазмуни тарих ва қидирувда топилмай қолади "
    "(фақат номи қолади). Ҳужжат мазмуни ҳеч қачон log файлларга ёзилмайди. "
    "Фақат администраторлар тизим статистикасини кўра олади - ҳужжат мазмунини "
    "эмас. Сизга рухсат берилмаган ҳужжатларни юкламанг.\n\n"
    "Буйруқлар: /start /help /history /search /settings /batch /about"
)

_ABOUT = (
    "ℹ️ <b>Бот ҳақида</b>\n\n"
    "<b>Document AI Bot</b> - PDF, сканланган ҳужжатлар ва расмларни (шу "
    "жумладан қўлёзма матнларни) сунъий интеллект (Google Gemini) ёрдамида "
    "таниб, тузилган DOCX, Excel ёки Markdown файлларига айлантирувчи "
    "Telegram бот.\n\n"
    "👨‍💻 <b>Муаллиф:</b> Бекзод Эшниязов\n"
    "📞 Телефон / Telegram: +998 97 778 10 09\n"
    "📧 Gmail: junior88.be@gmail.com\n\n"
    "Савол, таклиф ёки хатоликлар юзасидан юқоридаги алоқа маълумотлари "
    "орқали боғланинг."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(_WELCOME, reply_markup=main_menu_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP)


@router.message(Command("about"))
async def cmd_about(message: Message) -> None:
    await message.answer(_ABOUT)


@router.callback_query(F.data == MainMenuCallback.HELP)
async def cb_help(callback: CallbackQuery) -> None:
    message = editable_message(callback)
    if message is not None:
        await message.answer(_HELP)
    await callback.answer()


@router.callback_query(F.data == MainMenuCallback.ABOUT)
async def cb_about(callback: CallbackQuery) -> None:
    message = editable_message(callback)
    if message is not None:
        await message.answer(_ABOUT)
    await callback.answer()


@router.callback_query(F.data == MainMenuCallback.UPLOAD_DOCUMENT)
async def cb_upload_document(callback: CallbackQuery) -> None:
    message = editable_message(callback)
    if message is not None:
        await message.answer("📤 Энди менга PDF ҳужжат юборинг.")
    await callback.answer()


@router.callback_query(F.data == MainMenuCallback.UPLOAD_IMAGE)
async def cb_upload_image(callback: CallbackQuery) -> None:
    message = editable_message(callback)
    if message is not None:
        await message.answer("📷 Энди менга расм (JPG/PNG) юборинг.")
    await callback.answer()


@router.callback_query(
    F.data.in_(
        {
            MainMenuCallback.CREATE_DOCX,
            MainMenuCallback.CREATE_XLSX,
            MainMenuCallback.CREATE_MD,
            MainMenuCallback.AUTO_FORMAT,
        }
    )
)
async def cb_format_shortcut(callback: CallbackQuery) -> None:
    message = editable_message(callback)
    if message is not None:
        await message.answer(
            "Аввал менга ҳужжат ёки расм юборинг - шундан сўнг қайси форматни "
            "хоҳлашингизни сўрайман."
        )
    await callback.answer()
