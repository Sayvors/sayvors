"""Sayvors transactional email templates.

Design source: the bilingual email kit (welcome / OTP / reset / newsletter)
provided in the brand downloads. Same visual language:

* lavender page, white 600px card with a 20px radius
* purple → magenta → coral hero band
* Arabic-first heading with an English subheading
* soft note surfaces, pill buttons, text-only footer
* table-based layout with inline styles for email clients

Every value that can contain user input is escaped by the caller; the helpers
here only assemble markup.
"""
from __future__ import annotations

from datetime import datetime, timezone

PAGE_BG = "#F4F1FA"
CARD_BG = "#FFFFFF"
HERO_FROM = "#3B1470"
HERO_TO = "#8A2F8F"
ACCENT = "#FF6B5B"
INK = "#1A1033"
BODY = "#4A4266"
MUTED = "#7C7399"
SOFT = "#F6F2FE"
LINE = "#EEE8F8"
NOTE_BG = "#FFF4F1"
NOTE_TEXT = "#5A3A38"

SANS = "'Segoe UI',Helvetica,Arial,sans-serif"
ARABIC = "'Segoe UI',Tahoma,'Noto Naskh Arabic','Geeza Pro',Arial,sans-serif"


def icon_url(frontend_url: str) -> str:
    base = (frontend_url or "").rstrip("/")
    return f"{base}/Sayvors_Icon.png" if base else "/Sayvors_Icon.png"


def _cta(label: str, url: str, *, arabic: bool = False) -> str:
    family = ARABIC if arabic else SANS
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:26px auto 8px;">
      <tr><td align="center" style="border-radius:999px;background-color:{HERO_TO};background-image:linear-gradient(90deg,{HERO_FROM} 0%,{HERO_TO} 55%,{ACCENT} 100%);">
        <a href="{url}" style="display:inline-block;padding:15px 38px;font-family:{family};font-size:15px;line-height:20px;font-weight:700;color:#FFFFFF;text-decoration:none;border-radius:999px;">{label}</a>
      </td></tr>
    </table>"""


def shell(
    *,
    title_ar: str,
    title_en: str,
    preheader: str,
    body_html: str,
    frontend_url: str,
    support_email: str,
    help_url: str,
    privacy_url: str,
    hero_label_ar: str = "",
    hero_label_en: str = "",
    year: int | None = None,
) -> str:
    """The shared bilingual frame used by every transactional email."""
    year = year or datetime.now(timezone.utc).year
    logo = icon_url(frontend_url)
    hero_label = (
        f'<p dir="rtl" style="font-family:{ARABIC};margin:0 0 8px;font-size:13px;'
        f'line-height:20px;font-weight:700;color:#FFD9D3;text-align:center;">{hero_label_ar}</p>'
        if hero_label_ar
        else ""
    )
    hero_sub = (
        f'<p dir="ltr" style="font-family:{SANS};margin:10px 0 0;font-size:15px;'
        f'line-height:22px;color:#EADDF7;text-align:center;">{hero_label_en}</p>'
        if hero_label_en
        else ""
    )
    if title_ar:
        hero_title = (
            f'<h1 class="h1" dir="rtl" style="font-family:{ARABIC};margin:0;'
            f'font-size:31px;line-height:42px;font-weight:700;color:#FFFFFF;'
            f'text-align:center;">{title_ar}</h1>'
        )
    else:
        hero_title = (
            f'<h1 class="h1" dir="ltr" style="font-family:{SANS};margin:0;'
            f'font-size:29px;line-height:39px;font-weight:700;color:#FFFFFF;'
            f'letter-spacing:-0.4px;text-align:center;">{title_en}</h1>'
        )
    doc_title = f"{title_ar} | {title_en}" if title_ar else title_en
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
<title>{doc_title}</title>
<style>
  html,body{{margin:0 !important;padding:0 !important;width:100% !important;}}
  *{{-ms-text-size-adjust:100%;-webkit-text-size-adjust:100%;}}
  table,td{{mso-table-lspace:0pt;mso-table-rspace:0pt;border-collapse:collapse;}}
  img{{-ms-interpolation-mode:bicubic;border:0;outline:none;text-decoration:none;display:block;}}
  a{{text-decoration:none;}}
  a[x-apple-data-detectors]{{color:inherit !important;text-decoration:none !important;}}
  @media screen and (max-width:620px){{
    .container{{width:100% !important;}}
    .px{{padding-left:24px !important;padding-right:24px !important;}}
    .h1{{font-size:26px !important;line-height:36px !important;}}
    .stack{{display:block !important;width:100% !important;box-sizing:border-box;}}
    .stack-gap{{padding-top:10px !important;}}
  }}
</style>
</head>
<body style="margin:0;padding:0;background-color:{PAGE_BG};">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:{PAGE_BG};opacity:0;">
  {preheader}
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{PAGE_BG};">
<tr><td align="center" style="padding:36px 16px;">
<table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;">

  <!-- Brand -->
  <tr><td align="right" class="px" style="padding:0 6px 22px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" dir="ltr" align="right"><tr>
      <td valign="middle" style="padding-right:10px;"><img src="{logo}" width="38" height="38" alt="Sayvors" style="width:38px;height:38px;"></td>
      <td valign="middle" style="font-family:{SANS};font-size:25px;line-height:25px;font-weight:700;letter-spacing:-0.5px;color:{INK};">sayvors</td>
    </tr></table>
  </td></tr>

  <!-- Card -->
  <tr><td style="background-color:{CARD_BG};border-radius:20px;overflow:hidden;box-shadow:0 12px 40px rgba(59,20,112,0.10);">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">

    <!-- Hero -->
    <tr><td align="center" style="background-color:{HERO_FROM};background-image:linear-gradient(135deg,{HERO_FROM} 0%,{HERO_TO} 60%,{ACCENT} 100%);border-radius:20px 20px 0 0;padding:40px 32px 36px;">
      {hero_label}
      {hero_title}
      {hero_sub}
    </td></tr>

    <!-- Body -->
    <tr><td class="px" style="padding:34px 44px 12px;">{body_html}</td></tr>

    <!-- Footer -->
    <tr><td class="px" align="center" style="padding:10px 44px 34px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid {LINE};"><tr>
        <td align="center" style="padding-top:24px;">
          <p style="font-family:{SANS};margin:0 0 10px;font-size:11px;line-height:16px;font-weight:700;letter-spacing:3px;color:{HERO_TO};">EVERY LINE, ONE VOICE</p>
          <p dir="ltr" style="font-family:{SANS};margin:0 0 8px;font-size:12px;line-height:18px;color:{MUTED};">
            <a href="https://sayvors.com" style="color:{HERO_FROM};font-weight:600;">sayvors.com</a>
            &nbsp;&middot;&nbsp; <a href="{help_url}" style="color:{HERO_FROM};font-weight:600;">Help center</a>
            &nbsp;&middot;&nbsp; <a href="{privacy_url}" style="color:{HERO_FROM};font-weight:600;">Privacy</a>
          </p>
          <p dir="ltr" style="font-family:{SANS};margin:0 0 4px;font-size:12px;line-height:18px;color:{MUTED};">
            Need help? <a href="mailto:{support_email}" style="color:{HERO_FROM};font-weight:700;">{support_email}</a>
          </p>
          <p dir="ltr" style="font-family:{SANS};margin:0;font-size:11px;line-height:17px;color:#9A92B3;">
            Sayvors &middot; Riyadh, Saudi Arabia &middot; &copy; {year} Sayvors
          </p>
        </td>
      </tr></table>
    </td></tr>

  </table>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def otp_email(
    *,
    code: str,
    purpose: str,
    frontend_url: str,
    support_email: str,
    help_url: str,
    privacy_url: str,
) -> str:
    body = f"""
    <p dir="rtl" style="font-family:{ARABIC};margin:0 0 10px;font-size:15px;line-height:27px;color:{BODY};text-align:right;">
      مرحبًا، رمز التحقق الخاص بك في Sayvors هو:
    </p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 6px;"><tr>
      <td align="center" style="background-color:{SOFT};border:1px solid {LINE};border-radius:14px;padding:22px 12px;">
        <span dir="ltr" style="font-family:'SF Mono','Roboto Mono',Menlo,Consolas,'Courier New',monospace;font-size:34px;line-height:40px;font-weight:700;letter-spacing:9px;color:{INK};">{code}</span>
      </td>
    </tr></table>
    <p dir="rtl" style="font-family:{ARABIC};margin:16px 0 0;font-size:13.5px;line-height:24px;color:{MUTED};text-align:right;">
      ينتهي هذا الرمز خلال <strong style="color:{BODY};">10 دقائق</strong>. إن لم تطلبه، يمكنك تجاهل هذه الرسالة بأمان.
    </p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:24px;border-top:1px solid {LINE};"><tr>
      <td dir="ltr" align="left" style="padding-top:22px;">
        <p style="font-family:{SANS};margin:0 0 8px;font-size:11px;line-height:16px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{HERO_TO};">{purpose} code</p>
        <p style="font-family:{SANS};margin:0;font-size:14px;line-height:23px;color:{BODY};">
          This code expires in <strong>10 minutes</strong>. If you didn&rsquo;t request it, ignore this email.
        </p>
      </td>
    </tr></table>"""
    return shell(
        title_ar="تأكيد هويتك",
        title_en=f"Your Sayvors {purpose} code",
        preheader=f"رمز التحقق {code} ينتهي خلال 10 دقائق | Your code expires in 10 minutes",
        hero_label_ar="رمز التحقق",
        hero_label_en=f"Your Sayvors {purpose} code",
        body_html=body,
        frontend_url=frontend_url,
        support_email=support_email,
        help_url=help_url,
        privacy_url=privacy_url,
    )


def welcome_email(
    *,
    name: str,
    dashboard_url: str,
    frontend_url: str,
    support_email: str,
    help_url: str,
    privacy_url: str,
) -> str:
    body = f"""
    <p dir="rtl" style="font-family:{ARABIC};margin:0 0 18px;font-size:15.5px;line-height:28px;color:{BODY};text-align:right;">
      مرحبًا {name}،<br>
      يسعدنا انضمامك إلينا. حسابك جاهز الآن، وSayvors منصة واحدة تدير محادثات عملائك بالعربية وبلهجاتهم، على كل قناة، وبصوت علامتك التجارية.
    </p>
    {_cta("الذهاب إلى لوحة التحكم", dashboard_url, arabic=True)}
    <p dir="rtl" style="font-family:{ARABIC};margin:18px 0 8px;font-size:17px;line-height:27px;font-weight:700;color:{INK};text-align:right;">ثلاثة مسارات، منصة واحدة</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" dir="rtl"><tr>
      <td class="stack" width="33%" valign="top" style="padding:0 5px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
          <td dir="rtl" align="right" style="background-color:{SOFT};border-radius:14px;padding:15px;">
            <div style="width:26px;height:26px;line-height:26px;border-radius:13px;background-color:{HERO_TO};color:#fff;font-size:12px;font-weight:700;text-align:center;font-family:{SANS};">1</div>
            <div style="font-family:{ARABIC};margin-top:10px;font-size:14px;line-height:21px;font-weight:700;color:{INK};">الذكاء الصوتي</div>
            <div style="font-family:{ARABIC};margin-top:3px;font-size:12px;line-height:19px;color:{BODY};">يرد على المكالمات ويحوّلها للفريق المناسب</div>
          </td>
        </tr></table>
      </td>
      <td class="stack stack-gap" width="33%" valign="top" style="padding:0 5px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
          <td dir="rtl" align="right" style="background-color:{SOFT};border-radius:14px;padding:15px;">
            <div style="width:26px;height:26px;line-height:26px;border-radius:13px;background-color:{HERO_TO};color:#fff;font-size:12px;font-weight:700;text-align:center;font-family:{SANS};">2</div>
            <div style="font-family:{ARABIC};margin-top:10px;font-size:14px;line-height:21px;font-weight:700;color:{INK};">الذكاء الاجتماعي</div>
            <div style="font-family:{ARABIC};margin-top:3px;font-size:12px;line-height:19px;color:{BODY};">يدير الرسائل والتعليقات على القنوات</div>
          </td>
        </tr></table>
      </td>
      <td class="stack stack-gap" width="33%" valign="top" style="padding:0 5px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
          <td dir="rtl" align="right" style="background-color:{SOFT};border-radius:14px;padding:15px;">
            <div style="width:26px;height:26px;line-height:26px;border-radius:13px;background-color:{HERO_TO};color:#fff;font-size:12px;font-weight:700;text-align:center;font-family:{SANS};">3</div>
            <div style="font-family:{ARABIC};margin-top:10px;font-size:14px;line-height:21px;font-weight:700;color:{INK};">ذكاء الأعمال</div>
            <div style="font-family:{ARABIC};margin-top:3px;font-size:12px;line-height:19px;color:{BODY};">يتولى التقييمات والأسئلة وأعمال الاستقبال</div>
          </td>
        </tr></table>
      </td>
    </tr></table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:24px;"><tr>
      <td dir="rtl" align="right" style="background-color:{NOTE_BG};border-right:3px solid {ACCENT};border-radius:8px;padding:13px 16px;">
        <p style="font-family:{ARABIC};margin:0;font-size:13px;line-height:23px;color:{NOTE_TEXT};text-align:right;">
          نحتاج مساعدة؟ فريقنا جاهز على <a href="mailto:{support_email}" style="color:{HERO_FROM};font-weight:700;">{support_email}</a>.
        </p>
      </td>
    </tr></table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:26px;border-top:1px solid {LINE};"><tr>
      <td dir="ltr" align="left" style="padding-top:22px;">
        <p style="font-family:{SANS};margin:0 0 9px;font-size:11px;line-height:16px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{HERO_TO};">Registration successful</p>
        <p style="font-family:{SANS};margin:0 0 8px;font-size:19px;line-height:27px;font-weight:700;letter-spacing:-0.2px;color:{INK};">Welcome to Sayvors, {name}</p>
        <p style="font-family:{SANS};margin:0 0 14px;font-size:14px;line-height:23px;color:{BODY};">
          Your account is ready. Sayvors runs your customer conversations in Arabic, in every dialect, on every channel, in your brand&rsquo;s own voice.
        </p>
        <p style="font-family:{SANS};margin:0;font-size:13px;line-height:21px;color:{MUTED};">
          Need a hand? <a href="mailto:{support_email}" style="color:{HERO_FROM};font-weight:700;">{support_email}</a>
          or the <a href="{help_url}" style="color:{HERO_FROM};font-weight:700;">Help center</a>.
        </p>
      </td>
    </tr></table>"""
    return shell(
        title_ar="أهلًا بك في Sayvors",
        title_en="Welcome to Sayvors",
        preheader="تم إنشاء حسابك بنجاح. ابدأ الآن مع Sayvors. | Your account is ready.",
        hero_label_ar="تم التسجيل بنجاح",
        hero_label_en="Welcome to Sayvors — your account is ready.",
        body_html=body,
        frontend_url=frontend_url,
        support_email=support_email,
        help_url=help_url,
        privacy_url=privacy_url,
    )


def review_request_email(
    *,
    message: str,
    cta_url: str,
    frontend_url: str,
    support_email: str,
    help_url: str,
    privacy_url: str,
    email: str,
) -> str:
    from html import escape

    safe = escape(message or "")
    body = f"""
    <p dir="rtl" style="font-family:{ARABIC};margin:0 0 14px;font-size:15.5px;line-height:28px;color:{BODY};text-align:right;">
      رأيك يهمّنا، ويساعد عملاء آخرين على اختيارنا بثقة.
    </p>
    <p dir="ltr" style="font-family:{SANS};margin:0 0 22px;font-size:15px;line-height:24px;color:{BODY};">
      {safe}
    </p>
    {_cta("اترك تقييمك", cta_url, arabic=True)}
    <p dir="ltr" style="font-family:{SANS};margin:8px 0 0;font-size:12px;line-height:18px;color:{MUTED};text-align:center;">
      Leave your review
    </p>"""
    return shell(
        title_ar="شاركنا رأيك",
        title_en="How was your experience?",
        preheader="رأيك يساعدنا على التحسّن | Share your experience",
        hero_label_ar="تقييم سريع",
        hero_label_en="A quick review helps other customers",
        body_html=body,
        frontend_url=frontend_url,
        support_email=support_email,
        help_url=help_url,
        privacy_url=privacy_url,
    )


def reset_email(
    *,
    name: str,
    reset_url: str,
    frontend_url: str,
    support_email: str,
    help_url: str,
    privacy_url: str,
) -> str:
    body = f"""
    <p dir="rtl" style="font-family:{ARABIC};margin:0 0 16px;font-size:15.5px;line-height:28px;color:{BODY};text-align:right;">
      مرحبًا {name}،<br>
      وصلنا طلب لإعادة تعيين كلمة المرور الخاصة بحسابك في Sayvors. اضغط الزر لاختيار كلمة مرور جديدة، والرابط صالح لمدة ساعة واحدة.
    </p>
    {_cta("إعادة تعيين كلمة المرور", reset_url, arabic=True)}
    <p dir="ltr" style="font-family:{SANS};margin:10px 0 0;font-size:12px;line-height:18px;color:{MUTED};text-align:center;">
      Reset link valid for 1 hour
    </p>
    <p dir="rtl" style="font-family:{ARABIC};margin:18px 0 0;font-size:13px;line-height:23px;color:{MUTED};text-align:right;">
      إن لم تطلب هذا، يمكنك تجاهل الرسالة، ولن يتغير شيء في حسابك.
    </p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:22px;border-top:1px solid {LINE};"><tr>
      <td dir="ltr" align="left" style="padding-top:20px;">
        <p style="font-family:{SANS};margin:0 0 8px;font-size:14px;line-height:23px;color:{BODY};">
          Hi {name}, we received a request to reset your Sayvors password. The link above expires in <strong>1 hour</strong>.
          If you didn&rsquo;t ask for it, you can safely ignore this email.
        </p>
        <p style="font-family:{SANS};margin:8px 0 0;font-size:12px;line-height:18px;color:{MUTED};word-break:break-all;">
          Button not working? Paste this link: <a href="{reset_url}" style="color:{HERO_FROM};">{reset_url}</a>
        </p>
      </td>
    </tr></table>"""
    return shell(
        title_ar="هل نسيت كلمة المرور؟",
        title_en="Reset your Sayvors password",
        preheader="رابط إعادة تعيين كلمة المرور صالح لمدة ساعة | Reset your password",
        hero_label_ar="إعادة تعيين آمنة",
        hero_label_en="Reset your Sayvors password",
        body_html=body,
        frontend_url=frontend_url,
        support_email=support_email,
        help_url=help_url,
        privacy_url=privacy_url,
    )
