"""
tts.py
Turns story beats into a narrated voice track PLUS word-level timestamps
(needed for the punchy word-by-word captions this format relies on).

Two backends:
  - "edge"       Free, no API key, decent quality. Good for testing/volume.
  - "elevenlabs" Paid, much more natural/emotive. Swap in once you pick a plan.

Requires real internet access (this will NOT run inside the build sandbox --
run it on your own machine).
"""

import asyncio
import aiohttp
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

# ---- pick a default voice; browse more with Name                               Gender    ContentCategories      VoicePersonalities
# ---------------------------------  --------  ---------------------  --------------------------------------
# af-ZA-AdriNeural                   Female    General                Friendly, Positive
# af-ZA-WillemNeural                 Male      General                Friendly, Positive
# am-ET-AmehaNeural                  Male      General                Friendly, Positive
# am-ET-MekdesNeural                 Female    General                Friendly, Positive
# ar-AE-FatimaNeural                 Female    General                Friendly, Positive
# ar-AE-HamdanNeural                 Male      General                Friendly, Positive
# ar-BH-AliNeural                    Male      General                Friendly, Positive
# ar-BH-LailaNeural                  Female    General                Friendly, Positive
# ar-DZ-AminaNeural                  Female    General                Friendly, Positive
# ar-DZ-IsmaelNeural                 Male      General                Friendly, Positive
# ar-EG-SalmaNeural                  Female    General                Friendly, Positive
# ar-EG-ShakirNeural                 Male      General                Friendly, Positive
# ar-IQ-BasselNeural                 Male      General                Friendly, Positive
# ar-IQ-RanaNeural                   Female    General                Friendly, Positive
# ar-JO-SanaNeural                   Female    General                Friendly, Positive
# ar-JO-TaimNeural                   Male      General                Friendly, Positive
# ar-KW-FahedNeural                  Male      General                Friendly, Positive
# ar-KW-NouraNeural                  Female    General                Friendly, Positive
# ar-LB-LaylaNeural                  Female    General                Friendly, Positive
# ar-LB-RamiNeural                   Male      General                Friendly, Positive
# ar-LY-ImanNeural                   Female    General                Friendly, Positive
# ar-LY-OmarNeural                   Male      General                Friendly, Positive
# ar-MA-JamalNeural                  Male      General                Friendly, Positive
# ar-MA-MounaNeural                  Female    General                Friendly, Positive
# ar-OM-AbdullahNeural               Male      General                Friendly, Positive
# ar-OM-AyshaNeural                  Female    General                Friendly, Positive
# ar-QA-AmalNeural                   Female    General                Friendly, Positive
# ar-QA-MoazNeural                   Male      General                Friendly, Positive
# ar-SA-HamedNeural                  Male      General                Friendly, Positive
# ar-SA-ZariyahNeural                Female    General                Friendly, Positive
# ar-SY-AmanyNeural                  Female    General                Friendly, Positive
# ar-SY-LaithNeural                  Male      General                Friendly, Positive
# ar-TN-HediNeural                   Male      General                Friendly, Positive
# ar-TN-ReemNeural                   Female    General                Friendly, Positive
# ar-YE-MaryamNeural                 Female    General                Friendly, Positive
# ar-YE-SalehNeural                  Male      General                Friendly, Positive
# az-AZ-BabekNeural                  Male      General                Friendly, Positive
# az-AZ-BanuNeural                   Female    General                Friendly, Positive
# bg-BG-BorislavNeural               Male      General                Friendly, Positive
# bg-BG-KalinaNeural                 Female    General                Friendly, Positive
# bn-BD-NabanitaNeural               Female    General                Friendly, Positive
# bn-BD-PradeepNeural                Male      General                Friendly, Positive
# bn-IN-BashkarNeural                Male      General                Friendly, Positive
# bn-IN-TanishaaNeural               Female    General                Friendly, Positive
# bs-BA-GoranNeural                  Male      General                Friendly, Positive
# bs-BA-VesnaNeural                  Female    General                Friendly, Positive
# ca-ES-EnricNeural                  Male      General                Friendly, Positive
# ca-ES-JoanaNeural                  Female    General                Friendly, Positive
# cs-CZ-AntoninNeural                Male      General                Friendly, Positive
# cs-CZ-VlastaNeural                 Female    General                Friendly, Positive
# cy-GB-AledNeural                   Male      General                Friendly, Positive
# cy-GB-NiaNeural                    Female    General                Friendly, Positive
# da-DK-ChristelNeural               Female    General                Friendly, Positive
# da-DK-JeppeNeural                  Male      General                Friendly, Positive
# de-AT-IngridNeural                 Female    General                Friendly, Positive
# de-AT-JonasNeural                  Male      General                Friendly, Positive
# de-CH-JanNeural                    Male      General                Friendly, Positive
# de-CH-LeniNeural                   Female    General                Friendly, Positive
# de-DE-AmalaNeural                  Female    General                Friendly, Positive
# de-DE-ConradNeural                 Male      General                Friendly, Positive
# de-DE-FlorianMultilingualNeural    Male      General                Friendly, Positive
# de-DE-KatjaNeural                  Female    General                Friendly, Positive
# de-DE-KillianNeural                Male      General                Friendly, Positive
# de-DE-SeraphinaMultilingualNeural  Female    General                Friendly, Positive
# el-GR-AthinaNeural                 Female    General                Friendly, Positive
# el-GR-NestorasNeural               Male      General                Friendly, Positive
# en-AU-NatashaNeural                Female    General                Friendly, Positive
# en-AU-WilliamMultilingualNeural    Male      General                Friendly, Positive
# en-CA-ClaraNeural                  Female    General                Friendly, Positive
# en-CA-LiamNeural                   Male      General                Friendly, Positive
# en-GB-LibbyNeural                  Female    General                Friendly, Positive
# en-GB-MaisieNeural                 Female    General                Friendly, Positive
# en-GB-RyanNeural                   Male      General                Friendly, Positive
# en-GB-SoniaNeural                  Female    General                Friendly, Positive
# en-GB-ThomasNeural                 Male      General                Friendly, Positive
# en-HK-SamNeural                    Male      General                Friendly, Positive
# en-HK-YanNeural                    Female    General                Friendly, Positive
# en-IE-ConnorNeural                 Male      General                Friendly, Positive
# en-IE-EmilyNeural                  Female    General                Friendly, Positive
# en-IN-NeerjaExpressiveNeural       Female    General                Friendly, Positive
# en-IN-NeerjaNeural                 Female    General                Friendly, Positive
# en-IN-PrabhatNeural                Male      General                Friendly, Positive
# en-KE-AsiliaNeural                 Female    General                Friendly, Positive
# en-KE-ChilembaNeural               Male      General                Friendly, Positive
# en-NG-AbeoNeural                   Male      General                Friendly, Positive
# en-NG-EzinneNeural                 Female    General                Friendly, Positive
# en-NZ-MitchellNeural               Male      General                Friendly, Positive
# en-NZ-MollyNeural                  Female    General                Friendly, Positive
# en-PH-JamesNeural                  Male      General                Friendly, Positive
# en-PH-RosaNeural                   Female    General                Friendly, Positive
# en-SG-LunaNeural                   Female    General                Friendly, Positive
# en-SG-WayneNeural                  Male      General                Friendly, Positive
# en-TZ-ElimuNeural                  Male      General                Friendly, Positive
# en-TZ-ImaniNeural                  Female    General                Friendly, Positive
# en-US-AnaNeural                    Female    Cartoon, Conversation  Cute
# en-US-AndrewMultilingualNeural     Male      Conversation, Copilot  Warm, Confident, Authentic, Honest
# en-US-AndrewNeural                 Male      Conversation, Copilot  Warm, Confident, Authentic, Honest
# en-US-AriaNeural                   Female    News, Novel            Positive, Confident
# en-US-AvaMultilingualNeural        Female    Conversation, Copilot  Expressive, Caring, Pleasant, Friendly
# en-US-AvaNeural                    Female    Conversation, Copilot  Expressive, Caring, Pleasant, Friendly
# en-US-BrianMultilingualNeural      Male      Conversation, Copilot  Approachable, Casual, Sincere
# en-US-BrianNeural                  Male      Conversation, Copilot  Approachable, Casual, Sincere
# en-US-ChristopherNeural            Male      News, Novel            Reliable, Authority
# en-US-EmmaMultilingualNeural       Female    Conversation, Copilot  Cheerful, Clear, Conversational
# en-US-EmmaNeural                   Female    Conversation, Copilot  Cheerful, Clear, Conversational
# en-US-EricNeural                   Male      News, Novel            Rational
# en-US-GuyNeural                    Male      News, Novel            Passion
# en-US-JennyNeural                  Female    General                Friendly, Considerate, Comfort
# en-US-MichelleNeural               Female    News, Novel            Friendly, Pleasant
# en-US-RogerNeural                  Male      News, Novel            Lively
# en-US-SteffanNeural                Male      News, Novel            Rational
# en-ZA-LeahNeural                   Female    General                Friendly, Positive
# en-ZA-LukeNeural                   Male      General                Friendly, Positive
# es-AR-ElenaNeural                  Female    General                Friendly, Positive
# es-AR-TomasNeural                  Male      General                Friendly, Positive
# es-BO-MarceloNeural                Male      General                Friendly, Positive
# es-BO-SofiaNeural                  Female    General                Friendly, Positive
# es-CL-CatalinaNeural               Female    General                Friendly, Positive
# es-CL-LorenzoNeural                Male      General                Friendly, Positive
# es-CO-GonzaloNeural                Male      General                Friendly, Positive
# es-CO-SalomeNeural                 Female    General                Friendly, Positive
# es-CR-JuanNeural                   Male      General                Friendly, Positive
# es-CR-MariaNeural                  Female    General                Friendly, Positive
# es-CU-BelkysNeural                 Female    General                Friendly, Positive
# es-CU-ManuelNeural                 Male      General                Friendly, Positive
# es-DO-EmilioNeural                 Male      General                Friendly, Positive
# es-DO-RamonaNeural                 Female    General                Friendly, Positive
# es-EC-AndreaNeural                 Female    General                Friendly, Positive
# es-EC-LuisNeural                   Male      General                Friendly, Positive
# es-ES-AlvaroNeural                 Male      General                Friendly, Positive
# es-ES-ElviraNeural                 Female    General                Friendly, Positive
# es-ES-XimenaNeural                 Female    General                Friendly, Positive
# es-GQ-JavierNeural                 Male      General                Friendly, Positive
# es-GQ-TeresaNeural                 Female    General                Friendly, Positive
# es-GT-AndresNeural                 Male      General                Friendly, Positive
# es-GT-MartaNeural                  Female    General                Friendly, Positive
# es-HN-CarlosNeural                 Male      General                Friendly, Positive
# es-HN-KarlaNeural                  Female    General                Friendly, Positive
# es-MX-DaliaNeural                  Female    General                Friendly, Positive
# es-MX-JorgeNeural                  Male      General                Friendly, Positive
# es-NI-FedericoNeural               Male      General                Friendly, Positive
# es-NI-YolandaNeural                Female    General                Friendly, Positive
# es-PA-MargaritaNeural              Female    General                Friendly, Positive
# es-PA-RobertoNeural                Male      General                Friendly, Positive
# es-PE-AlexNeural                   Male      General                Friendly, Positive
# es-PE-CamilaNeural                 Female    General                Friendly, Positive
# es-PR-KarinaNeural                 Female    General                Friendly, Positive
# es-PR-VictorNeural                 Male      General                Friendly, Positive
# es-PY-MarioNeural                  Male      General                Friendly, Positive
# es-PY-TaniaNeural                  Female    General                Friendly, Positive
# es-SV-LorenaNeural                 Female    General                Friendly, Positive
# es-SV-RodrigoNeural                Male      General                Friendly, Positive
# es-US-AlonsoNeural                 Male      General                Friendly, Positive
# es-US-PalomaNeural                 Female    General                Friendly, Positive
# es-UY-MateoNeural                  Male      General                Friendly, Positive
# es-UY-ValentinaNeural              Female    General                Friendly, Positive
# es-VE-PaolaNeural                  Female    General                Friendly, Positive
# es-VE-SebastianNeural              Male      General                Friendly, Positive
# et-EE-AnuNeural                    Female    General                Friendly, Positive
# et-EE-KertNeural                   Male      General                Friendly, Positive
# fa-IR-DilaraNeural                 Female    General                Friendly, Positive
# fa-IR-FaridNeural                  Male      General                Friendly, Positive
# fi-FI-HarriNeural                  Male      General                Friendly, Positive
# fi-FI-NooraNeural                  Female    General                Friendly, Positive
# fil-PH-AngeloNeural                Male      General                Friendly, Positive
# fil-PH-BlessicaNeural              Female    General                Friendly, Positive
# fr-BE-CharlineNeural               Female    General                Friendly, Positive
# fr-BE-GerardNeural                 Male      General                Friendly, Positive
# fr-CA-AntoineNeural                Male      General                Friendly, Positive
# fr-CA-JeanNeural                   Male      General                Friendly, Positive
# fr-CA-SylvieNeural                 Female    General                Friendly, Positive
# fr-CA-ThierryNeural                Male      General                Friendly, Positive
# fr-CH-ArianeNeural                 Female    General                Friendly, Positive
# fr-CH-FabriceNeural                Male      General                Friendly, Positive
# fr-FR-DeniseNeural                 Female    General                Friendly, Positive
# fr-FR-EloiseNeural                 Female    General                Friendly, Positive
# fr-FR-HenriNeural                  Male      General                Friendly, Positive
# fr-FR-RemyMultilingualNeural       Male      General                Friendly, Positive
# fr-FR-VivienneMultilingualNeural   Female    General                Friendly, Positive
# ga-IE-ColmNeural                   Male      General                Friendly, Positive
# ga-IE-OrlaNeural                   Female    General                Friendly, Positive
# gl-ES-RoiNeural                    Male      General                Friendly, Positive
# gl-ES-SabelaNeural                 Female    General                Friendly, Positive
# gu-IN-DhwaniNeural                 Female    General                Friendly, Positive
# gu-IN-NiranjanNeural               Male      General                Friendly, Positive
# he-IL-AvriNeural                   Male      General                Friendly, Positive
# he-IL-HilaNeural                   Female    General                Friendly, Positive
# hi-IN-MadhurNeural                 Male      General                Friendly, Positive
# hi-IN-SwaraNeural                  Female    General                Friendly, Positive
# hr-HR-GabrijelaNeural              Female    General                Friendly, Positive
# hr-HR-SreckoNeural                 Male      General                Friendly, Positive
# hu-HU-NoemiNeural                  Female    General                Friendly, Positive
# hu-HU-TamasNeural                  Male      General                Friendly, Positive
# id-ID-ArdiNeural                   Male      General                Friendly, Positive
# id-ID-GadisNeural                  Female    General                Friendly, Positive
# is-IS-GudrunNeural                 Female    General                Friendly, Positive
# is-IS-GunnarNeural                 Male      General                Friendly, Positive
# it-IT-DiegoNeural                  Male      General                Friendly, Positive
# it-IT-ElsaNeural                   Female    General                Friendly, Positive
# it-IT-GiuseppeMultilingualNeural   Male      General                Friendly, Positive
# it-IT-IsabellaNeural               Female    General                Friendly, Positive
# iu-Cans-CA-SiqiniqNeural           Female    General                Friendly, Positive
# iu-Cans-CA-TaqqiqNeural            Male      General                Friendly, Positive
# iu-Latn-CA-SiqiniqNeural           Female    General                Friendly, Positive
# iu-Latn-CA-TaqqiqNeural            Male      General                Friendly, Positive
# ja-JP-KeitaNeural                  Male      General                Friendly, Positive
# ja-JP-NanamiNeural                 Female    General                Friendly, Positive
# jv-ID-DimasNeural                  Male      General                Friendly, Positive
# jv-ID-SitiNeural                   Female    General                Friendly, Positive
# ka-GE-EkaNeural                    Female    General                Friendly, Positive
# ka-GE-GiorgiNeural                 Male      General                Friendly, Positive
# kk-KZ-AigulNeural                  Female    General                Friendly, Positive
# kk-KZ-DauletNeural                 Male      General                Friendly, Positive
# km-KH-PisethNeural                 Male      General                Friendly, Positive
# km-KH-SreymomNeural                Female    General                Friendly, Positive
# kn-IN-GaganNeural                  Male      General                Friendly, Positive
# kn-IN-SapnaNeural                  Female    General                Friendly, Positive
# ko-KR-HyunsuMultilingualNeural     Male      General                Friendly, Positive
# ko-KR-InJoonNeural                 Male      General                Friendly, Positive
# ko-KR-SunHiNeural                  Female    General                Friendly, Positive
# lo-LA-ChanthavongNeural            Male      General                Friendly, Positive
# lo-LA-KeomanyNeural                Female    General                Friendly, Positive
# lt-LT-LeonasNeural                 Male      General                Friendly, Positive
# lt-LT-OnaNeural                    Female    General                Friendly, Positive
# lv-LV-EveritaNeural                Female    General                Friendly, Positive
# lv-LV-NilsNeural                   Male      General                Friendly, Positive
# mk-MK-AleksandarNeural             Male      General                Friendly, Positive
# mk-MK-MarijaNeural                 Female    General                Friendly, Positive
# ml-IN-MidhunNeural                 Male      General                Friendly, Positive
# ml-IN-SobhanaNeural                Female    General                Friendly, Positive
# mn-MN-BataaNeural                  Male      General                Friendly, Positive
# mn-MN-YesuiNeural                  Female    General                Friendly, Positive
# mr-IN-AarohiNeural                 Female    General                Friendly, Positive
# mr-IN-ManoharNeural                Male      General                Friendly, Positive
# ms-MY-OsmanNeural                  Male      General                Friendly, Positive
# ms-MY-YasminNeural                 Female    General                Friendly, Positive
# mt-MT-GraceNeural                  Female    General                Friendly, Positive
# mt-MT-JosephNeural                 Male      General                Friendly, Positive
# my-MM-NilarNeural                  Female    General                Friendly, Positive
# my-MM-ThihaNeural                  Male      General                Friendly, Positive
# nb-NO-FinnNeural                   Male      General                Friendly, Positive
# nb-NO-PernilleNeural               Female    General                Friendly, Positive
# ne-NP-HemkalaNeural                Female    General                Friendly, Positive
# ne-NP-SagarNeural                  Male      General                Friendly, Positive
# nl-BE-ArnaudNeural                 Male      General                Friendly, Positive
# nl-BE-DenaNeural                   Female    General                Friendly, Positive
# nl-NL-ColetteNeural                Female    General                Friendly, Positive
# nl-NL-FennaNeural                  Female    General                Friendly, Positive
# nl-NL-MaartenNeural                Male      General                Friendly, Positive
# pl-PL-MarekNeural                  Male      General                Friendly, Positive
# pl-PL-ZofiaNeural                  Female    General                Friendly, Positive
# ps-AF-GulNawazNeural               Male      General                Friendly, Positive
# ps-AF-LatifaNeural                 Female    General                Friendly, Positive
# pt-BR-AntonioNeural                Male      General                Friendly, Positive
# pt-BR-FranciscaNeural              Female    General                Friendly, Positive
# pt-BR-ThalitaMultilingualNeural    Female    General                Friendly, Positive
# pt-PT-DuarteNeural                 Male      General                Friendly, Positive
# pt-PT-RaquelNeural                 Female    General                Friendly, Positive
# ro-RO-AlinaNeural                  Female    General                Friendly, Positive
# ro-RO-EmilNeural                   Male      General                Friendly, Positive
# ru-RU-DmitryNeural                 Male      General                Friendly, Positive
# ru-RU-SvetlanaNeural               Female    General                Friendly, Positive
# si-LK-SameeraNeural                Male      General                Friendly, Positive
# si-LK-ThiliniNeural                Female    General                Friendly, Positive
# sk-SK-LukasNeural                  Male      General                Friendly, Positive
# sk-SK-ViktoriaNeural               Female    General                Friendly, Positive
# sl-SI-PetraNeural                  Female    General                Friendly, Positive
# sl-SI-RokNeural                    Male      General                Friendly, Positive
# so-SO-MuuseNeural                  Male      General                Friendly, Positive
# so-SO-UbaxNeural                   Female    General                Friendly, Positive
# sq-AL-AnilaNeural                  Female    General                Friendly, Positive
# sq-AL-IlirNeural                   Male      General                Friendly, Positive
# sr-RS-NicholasNeural               Male      General                Friendly, Positive
# sr-RS-SophieNeural                 Female    General                Friendly, Positive
# su-ID-JajangNeural                 Male      General                Friendly, Positive
# su-ID-TutiNeural                   Female    General                Friendly, Positive
# sv-SE-MattiasNeural                Male      General                Friendly, Positive
# sv-SE-SofieNeural                  Female    General                Friendly, Positive
# sw-KE-RafikiNeural                 Male      General                Friendly, Positive
# sw-KE-ZuriNeural                   Female    General                Friendly, Positive
# sw-TZ-DaudiNeural                  Male      General                Friendly, Positive
# sw-TZ-RehemaNeural                 Female    General                Friendly, Positive
# ta-IN-PallaviNeural                Female    General                Friendly, Positive
# ta-IN-ValluvarNeural               Male      General                Friendly, Positive
# ta-LK-KumarNeural                  Male      General                Friendly, Positive
# ta-LK-SaranyaNeural                Female    General                Friendly, Positive
# ta-MY-KaniNeural                   Female    General                Friendly, Positive
# ta-MY-SuryaNeural                  Male      General                Friendly, Positive
# ta-SG-AnbuNeural                   Male      General                Friendly, Positive
# ta-SG-VenbaNeural                  Female    General                Friendly, Positive
# te-IN-MohanNeural                  Male      General                Friendly, Positive
# te-IN-ShrutiNeural                 Female    General                Friendly, Positive
# th-TH-NiwatNeural                  Male      General                Friendly, Positive
# th-TH-PremwadeeNeural              Female    General                Friendly, Positive
# tr-TR-AhmetNeural                  Male      General                Friendly, Positive
# tr-TR-EmelNeural                   Female    General                Friendly, Positive
# uk-UA-OstapNeural                  Male      General                Friendly, Positive
# uk-UA-PolinaNeural                 Female    General                Friendly, Positive
# ur-IN-GulNeural                    Female    General                Friendly, Positive
# ur-IN-SalmanNeural                 Male      General                Friendly, Positive
# ur-PK-AsadNeural                   Male      General                Friendly, Positive
# ur-PK-UzmaNeural                   Female    General                Friendly, Positive
# uz-UZ-MadinaNeural                 Female    General                Friendly, Positive
# uz-UZ-SardorNeural                 Male      General                Friendly, Positive
# vi-VN-HoaiMyNeural                 Female    General                Friendly, Positive
# vi-VN-NamMinhNeural                Male      General                Friendly, Positive
# zh-CN-XiaoxiaoNeural               Female    News, Novel            Warm
# zh-CN-XiaoyiNeural                 Female    Cartoon, Novel         Lively
# zh-CN-YunjianNeural                Male      Sports,  Novel         Passion
# zh-CN-YunxiNeural                  Male      Novel                  Lively, Sunshine
# zh-CN-YunxiaNeural                 Male      Cartoon, Novel         Cute
# zh-CN-YunyangNeural                Male      News                   Professional, Reliable
# zh-CN-liaoning-XiaobeiNeural       Female    Dialect                Humorous
# zh-CN-shaanxi-XiaoniNeural         Female    Dialect                Bright
# zh-HK-HiuGaaiNeural                Female    General                Friendly, Positive
# zh-HK-HiuMaanNeural                Female    General                Friendly, Positive
# zh-HK-WanLungNeural                Male      General                Friendly, Positive
# zh-TW-HsiaoChenNeural              Female    General                Friendly, Positive
# zh-TW-HsiaoYuNeural                Female    General                Friendly, Positive
# zh-TW-YunJheNeural                 Male      General                Friendly, Positive
# zu-ZA-ThandoNeural                 Female    General                Friendly, Positive
# zu-ZA-ThembaNeural                 Male      General                Friendly, Positive ----
DEFAULT_EDGE_VOICE = "en-US-AndrewMultilingualNeural"  # natural/dynamic, far less monotone than GuyNeural
# alt options: en-US-BrianMultilingualNeural, en-US-ChristopherNeural, en-US-AriaNeural
DEFAULT_EDGE_RATE = "+15%"                   # fast like the winning channels, still clear
                                             # (word-by-word captions carry comprehension)

# Retry settings for Edge TTS rate limits (429)
MAX_RETRIES = 8
INITIAL_RETRY_DELAY = 20  # seconds
MAX_RETRY_DELAY = 60  # seconds


@dataclass
class WordTiming:
    word: str
    start_ms: int
    end_ms: int


import re


def make_speakable(text: str) -> str:
    """
    Rewrite written-style tokens into what a narrator would actually say,
    so the TTS read flows naturally. Written surfaces (cards, titles) keep
    the original text -- this transform is for narration only.
    """
    # "r/AITAH" or bare "AITAH"/"AITA" -> spoken form
    text = re.sub(r"\br/AITAH?\b", "AITAH", text)
    text = re.sub(r"\bAITAH?\b", "am I the a-hole", text)
    # Capitalize if it starts a sentence
    text = re.sub(r"(^|[.!?]\s+)am I", lambda m: m.group(1) + "Am I", text)
    # "(28F)" / "(34M)" age tags -> "28, female," / "34, male,"
    text = re.sub(r"\s*\((\d+)\s*F\)", lambda m: f", {m.group(1)}, female,", text)
    text = re.sub(r"\s*\((\d+)\s*M\)", lambda m: f", {m.group(1)}, male,", text)
    return text


async def _edge_tts_generate(text: str, out_path: Path, voice: str = DEFAULT_EDGE_VOICE, rate: str = DEFAULT_EDGE_RATE):
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    submaker = edge_tts.SubMaker()
    words: list[WordTiming] = []

    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append(WordTiming(
                    word=chunk["text"],
                    start_ms=int(chunk["offset"] / 10_000),
                    end_ms=int((chunk["offset"] + chunk["duration"]) / 10_000),
                ))
    return words


def generate_voice_edge(text: str, out_path: str | Path, voice: str = DEFAULT_EDGE_VOICE, rate: str = DEFAULT_EDGE_RATE) -> list[WordTiming]:
    """
    Generate voice using Edge TTS with retry logic for rate limits (429).
    
    Edge TTS is free but rate-limited. On 429 errors, we retry with
    exponential backoff up to MAX_RETRIES times.
    """
    out_path = Path(out_path)
    
    last_error = None
    delay = INITIAL_RETRY_DELAY
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            words = asyncio.run(_edge_tts_generate(text, out_path, voice, rate))
            return words
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            
            # Check if this is a rate limit error (429)
            if (hasattr(e, "status") and e.status == 429) or "429" in error_str or "rate" in error_str or "too many" in error_str:
                if attempt < MAX_RETRIES:
                    print(f"Edge TTS rate limited (429), retry {attempt + 1}/{MAX_RETRIES} in {delay}s...", file=__import__("sys").stderr)
                    time.sleep(delay)
                    delay = min(delay * 2, MAX_RETRY_DELAY)
                    continue
            
            # For non-rate-limit errors or max retries exceeded, raise immediately
            break
    
    # If we get here, all retries failed or it wasn't a rate limit error
    if last_error:
        raise last_error
    raise RuntimeError("Edge TTS generation failed with unknown error")


def generate_voice_elevenlabs(text: str, out_path: str | Path, api_key: str, voice_id: str) -> list[WordTiming]:
    """
    Higher quality option. Sign up at https://elevenlabs.io, grab an API key
    and a voice_id. This uses the 'with timestamps' endpoint so we still get
    word-level timing for captions.
    """
    import requests
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    resp = requests.post(
        url,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
    )
    resp.raise_for_status()
    data = resp.json()

    import base64
    Path(out_path).write_bytes(base64.b64decode(data["audio_base64"]))

    # Reconstruct word-level timing from character alignment
    chars = data["alignment"]["characters"]
    starts = data["alignment"]["character_start_times_seconds"]
    ends = data["alignment"]["character_end_times_seconds"]

    words, cur_word, w_start = [], "", None
    for ch, s, e in zip(chars, starts, ends):
        if ch == " ":
            if cur_word:
                words.append(WordTiming(cur_word, int(w_start * 1000), int(e * 1000)))
                cur_word, w_start = "", None
        else:
            if w_start is None:
                w_start = s
            cur_word += ch
    if cur_word:
        words.append(WordTiming(cur_word, int(w_start * 1000), int(ends[-1] * 1000)))
    return words


def save_word_timings(words: list[WordTiming], path: str | Path):
    Path(path).write_text(json.dumps([asdict(w) for w in words], indent=2))


if __name__ == "__main__":
    sample = "This is a test of the free edge text to speech voice."
    ts = generate_voice_edge(sample, "voice/test.mp3")
    save_word_timings(ts, "voice/test_timings.json")
    print(f"Generated {len(ts)} word timings")
