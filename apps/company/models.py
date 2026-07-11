from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal

from .statutory import default_payroll_tax_brackets


# ─── Colour theme choices ────────────────────────────────────────────────────
THEME_CHOICES = [
    ("forest",  "Forest Green & Gold  (default)"),
    ("ocean",   "Ocean Blue & Silver"),
    ("royal",   "Royal Purple & Amber"),
    ("ember",   "Ember Red & Copper"),
    ("slate",   "Slate Grey & Teal"),
    ("midnight","Midnight Black & Gold"),
]

CURRENCY_CHOICES = [
    ("GHS", "Ghana Cedi (GHS ₵)"),
    ("NGN", "Nigerian Naira (NGN ₦)"),
    ("KES", "Kenyan Shilling (KES)"),
    ("UGX", "Ugandan Shilling (UGX)"),
    ("ZAR", "South African Rand (ZAR R)"),
    ("XOF", "West African CFA (XOF)"),
    ("USD", "US Dollar (USD $)"),
    ("GBP", "British Pound (GBP £)"),
    ("EUR", "Euro (EUR €)"),
    ("TZS", "Tanzanian Shilling (TZS)"),
    ("RWF", "Rwandan Franc (RWF)"),
    ("ETB", "Ethiopian Birr (ETB)"),
    ("ZMW", "Zambian Kwacha (ZMW)"),
    ("MWK", "Malawian Kwacha (MWK)"),
    ("SLL", "Sierra Leonean Leone (SLL)"),
]

REPAYMENT_CYCLE_CHOICES = [
    ("weekly",    "Weekly"),
    ("biweekly",  "Bi-Weekly"),
    ("monthly",   "Monthly"),
]

DEFAULT_LOAN_TIERS_JSON = [
    {"code": "BRONZE",    "label": "Bronze",    "min": 0,      "max": 3000},
    {"code": "SILVER",    "label": "Silver",    "min": 3001,   "max": 5000},
    {"code": "GOLD",      "label": "Gold",      "min": 5001,   "max": 10000},
    {"code": "PLATINUM",  "label": "Platinum",  "min": 10001,  "max": 15000},
    {"code": "DIAMOND",   "label": "Diamond",   "min": 15001,  "max": 20000},
    {"code": "EXECUTIVE", "label": "Executive", "min": 20001,  "max": 999999999},
]


class CompanyProfile(models.Model):
    """
    Single-row table.  Only one instance should exist (pk=1).
    Use CompanyProfile.get_solo() everywhere.
    """

    # ── Identity ──────────────────────────────────────────────
    company_name    = models.CharField(max_length=120, default="My Micro-Credit",
                                       help_text="Your business / brand name.")
    tagline         = models.CharField(max_length=180, blank=True,
                                       default="Micro-Credit Enterprise",
                                       help_text="Short tagline shown below the brand name.")
    description     = models.TextField(blank=True,
                                       default=(
                                           "Premium operations environment for portfolio monitoring, "
                                           "borrower management, recovery tracking, and field execution."
                                       ),
                                       help_text="One-paragraph description used on the dashboard hero.")

    logo            = models.ImageField(upload_to="company/logos/", blank=True,
                                        help_text="Optional logo image (shown in topbar).")
    favicon         = models.ImageField(upload_to="company/favicons/", blank=True,
                                        help_text="Optional favicon (.ico / .png, 32×32 recommended).")

    # ── Contact ───────────────────────────────────────────────
    phone           = models.CharField(max_length=30, blank=True)
    email           = models.EmailField(blank=True)
    address         = models.CharField(max_length=255, blank=True)
    website         = models.URLField(blank=True)

    # ── Locale & currency ─────────────────────────────────────
    currency_code   = models.CharField(max_length=6, choices=CURRENCY_CHOICES, default="GHS",
                                       help_text="Currency used across all monetary displays.")
    currency_symbol = models.CharField(max_length=6, default="GHS",
                                       help_text="Symbol or prefix shown on amounts, e.g. '₵', 'GHS', '$'.")
    country         = models.CharField(max_length=80, blank=True, default="Ghana")
    timezone_name   = models.CharField(max_length=60, blank=True, default="Africa/Accra",
                                       help_text="Django timezone string, e.g. 'Africa/Accra'.")

    # ── Operations ────────────────────────────────────────────
    repayment_cycle = models.CharField(max_length=12, choices=REPAYMENT_CYCLE_CHOICES,
                                       default="weekly",
                                       help_text="Default repayment cadence for new loans.")
    default_loan_duration = models.PositiveIntegerField(
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(520)],
        help_text="Default number of repayment periods for new loans.",
    )
    overdue_grace_periods = models.PositiveIntegerField(
        default=6,
        validators=[MinValueValidator(1), MaxValueValidator(52)],
        help_text=(
            "Number of missed repayment periods before a loan is marked DEFAULT "
            "and the borrower flagged as BAD."
        ),
    )

    # ── Statutory & tax configuration ────────────────────────
    payroll_tax_enabled = models.BooleanField(
        default=True,
        help_text="Automatically calculate employee PAYE during payroll generation.",
    )
    payroll_employee_pension_enabled = models.BooleanField(
        default=True,
        help_text="Deduct employee pension contributions from payroll automatically.",
    )
    payroll_employer_pension_enabled = models.BooleanField(
        default=True,
        help_text="Accrue employer pension contributions as an additional payroll cost.",
    )
    payroll_welfare_enabled = models.BooleanField(
        default=False,
        help_text="Apply staff welfare deductions automatically during payroll runs.",
    )
    payroll_personal_relief_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Monthly relief deducted before PAYE is calculated.",
    )
    payroll_employee_pension_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.50"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Employee pension deduction as a percentage of basic salary.",
    )
    payroll_employer_pension_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("13.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Employer pension contribution as a percentage of basic salary.",
    )
    payroll_welfare_deduction_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Optional staff welfare deduction as a percentage of gross pay.",
    )
    payroll_welfare_fixed_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Optional flat welfare deduction applied to each payroll line.",
    )
    payroll_tax_brackets = models.JSONField(
        default=default_payroll_tax_brackets,
        blank=True,
        help_text='JSON array of tax bands: [{"up_to":"490.00","rate":"0.00","label":"First 490"}, ...]',
    )
    paye_payable_account_code = models.CharField(
        max_length=20,
        default="2051",
        help_text="Ledger code used for PAYE liabilities.",
    )
    employee_pension_payable_account_code = models.CharField(
        max_length=20,
        default="2052",
        help_text="Ledger code used for employee pension liabilities.",
    )
    employer_pension_payable_account_code = models.CharField(
        max_length=20,
        default="2053",
        help_text="Ledger code used for employer pension liabilities.",
    )
    welfare_payable_account_code = models.CharField(
        max_length=20,
        default="2054",
        help_text="Ledger code used for staff welfare or union deductions.",
    )
    employer_statutory_expense_account_code = models.CharField(
        max_length=20,
        default="5035",
        help_text="Expense ledger used for employer statutory contributions.",
    )
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Standard VAT rate used by the business.",
    )
    nhil_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("2.50"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="National Health Insurance Levy rate.",
    )
    getfund_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("2.50"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="GETFund levy rate.",
    )
    withholding_tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Default withholding tax rate for supplier or contractor payments.",
    )
    corporate_income_tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("25.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Reference corporate income tax rate for management reporting.",
    )

    # ── Loan tiers (JSON) ─────────────────────────────────────
    loan_tiers      = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "JSON array of tier objects: "
            '[{"code":"BRONZE","label":"Bronze","min":0,"max":3000}, ...]'
        ),
    )

    # ── Borrower languages ─────────────────────────────────────
    borrower_languages = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'JSON array of language strings available on borrower records, '
            'e.g. ["Twi","Ewe","Ga","Hausa"]'
        ),
    )

    # ── Public Website ───────────────────────────────────────
    # Hero section
    hero_headline   = models.CharField(max_length=200, blank=True,
                                       default="Financial Freedom Starts Here",
                                       help_text="Main headline on the public website hero section.")
    hero_subheadline = models.CharField(max_length=300, blank=True,
                                        default="Fast, fair, and transparent micro-credit for individuals and businesses.",
                                        help_text="Supporting text under the hero headline.")
    hero_image      = models.ImageField(upload_to="company/website/", blank=True,
                                        help_text="Background or feature image for the hero section.")
    hero_cta_text   = models.CharField(max_length=80, blank=True, default="Apply for a Loan",
                                       help_text="Hero call-to-action button text.")
    hero_cta_url    = models.URLField(blank=True,
                                      help_text="URL the CTA button links to (leave blank to use contact section).")

    # About / mission
    mission_statement = models.TextField(blank=True,
                                         default="To provide accessible, responsible micro-credit solutions that empower individuals and small businesses to grow, build assets, and achieve lasting financial stability.",
                                         help_text="Mission statement displayed in the About section.")
    vision_statement  = models.TextField(blank=True,
                                         default="A community where every entrepreneur has access to the capital they need to thrive.",
                                         help_text="Vision statement displayed in the About section.")
    years_in_business = models.PositiveIntegerField(default=0, blank=True,
                                                     help_text="Years in operation shown as a stat on the website (0 to hide).")
    clients_served    = models.PositiveIntegerField(default=0, blank=True,
                                                     help_text="Total clients/borrowers served (0 to hide).")
    loans_disbursed_display = models.CharField(max_length=40, blank=True,
                                               help_text="e.g. 'GHS 2.5M' — shown on the website stats bar (leave blank to hide).")
    about_image       = models.ImageField(upload_to="company/website/", blank=True,
                                          help_text="Image displayed in the About section.")

    # Services / loan products (JSON list of service objects)
    services          = models.JSONField(
        default=list, blank=True,
        help_text=(
            'JSON array of service objects: '
            '[{"title":"Quick Loans","icon":"⚡","description":"...","highlight":false}, ...]'
        ),
    )

    # Loan tiers display on website (uses loan_tiers but can have richer descriptions)
    tier_descriptions = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Optional extra descriptions per tier for the website: '
            '[{"code":"BRONZE","tagline":"Perfect for getting started","features":["..."]}, ...]'
        ),
    )

    # Testimonials
    testimonials      = models.JSONField(
        default=list, blank=True,
        help_text=(
            'JSON array: '
            '[{"name":"Ama Owusu","role":"Trader, Kumasi","quote":"...","avatar_initials":"AO"}, ...]'
        ),
    )

    # FAQ
    faqs              = models.JSONField(
        default=list, blank=True,
        help_text=(
            'JSON array: [{"question":"How do I apply?","answer":"..."}, ...]'
        ),
    )

    # Social media & contact for website
    whatsapp_number   = models.CharField(max_length=30, blank=True,
                                          help_text="WhatsApp number for the website contact widget (include country code, e.g. +233...).")
    facebook_url      = models.URLField(blank=True, help_text="Facebook page URL.")
    instagram_url     = models.URLField(blank=True, help_text="Instagram profile URL.")
    twitter_url       = models.URLField(blank=True, help_text="Twitter/X profile URL.")
    youtube_url       = models.URLField(blank=True, help_text="YouTube channel URL.")

    # Website appearance
    show_loan_calculator = models.BooleanField(default=True,
                                                help_text="Show the interactive loan calculator on the website.")
    show_testimonials    = models.BooleanField(default=True,
                                               help_text="Show the testimonials section on the website.")
    show_faqs            = models.BooleanField(default=True,
                                               help_text="Show the FAQ section on the website.")
    primary_cta_color    = models.CharField(max_length=20, blank=True,
                                             help_text="Override CTA button color (hex, e.g. #3a5a1e). Leave blank to use theme color.")


    # ── Gallery (up to 10 images) ─────────────────────────────
    gallery_image_1  = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 1")
    gallery_caption_1 = models.CharField(max_length=120, blank=True, help_text="Caption for gallery image 1")
    gallery_image_2  = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 2")
    gallery_caption_2 = models.CharField(max_length=120, blank=True)
    gallery_image_3  = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 3")
    gallery_caption_3 = models.CharField(max_length=120, blank=True)
    gallery_image_4  = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 4")
    gallery_caption_4 = models.CharField(max_length=120, blank=True)
    gallery_image_5  = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 5")
    gallery_caption_5 = models.CharField(max_length=120, blank=True)
    gallery_image_6  = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 6")
    gallery_caption_6 = models.CharField(max_length=120, blank=True)
    gallery_image_7  = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 7")
    gallery_caption_7 = models.CharField(max_length=120, blank=True)
    gallery_image_8  = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 8")
    gallery_caption_8 = models.CharField(max_length=120, blank=True)
    gallery_image_9  = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 9")
    gallery_caption_9 = models.CharField(max_length=120, blank=True)
    gallery_image_10 = models.ImageField(upload_to="company/gallery/", blank=True, help_text="Gallery image 10")
    gallery_caption_10 = models.CharField(max_length=120, blank=True)

    # ── About page extras ─────────────────────────────────────
    goals             = models.JSONField(
        default=list, blank=True,
        help_text='JSON array: [{"title":"Financial Inclusion","description":"...","icon":"🎯"}, ...]'
    )
    management_team   = models.JSONField(
        default=list, blank=True,
        help_text='JSON array: [{"name":"John Doe","title":"CEO","bio":"...","initials":"JD"}, ...]'
    )
    about_image_2     = models.ImageField(upload_to="company/website/", blank=True, help_text="Second about page image")
    about_image_3     = models.ImageField(upload_to="company/website/", blank=True, help_text="Third about page image")

    # ── Branches / locations ──────────────────────────────────
    branches          = models.JSONField(
        default=list, blank=True,
        help_text=(
            'JSON array: [{"name":"Head Office","address":"123 Main St","phone":"+233...","email":"...","lat":"5.6037","lng":"-0.1870","is_head_office":true}, ...]'
        ),
    )

    # ── Website branding & colours ────────────────────────────
    # Colours (hex values, leave blank to use theme defaults)
    site_primary_color   = models.CharField(max_length=20, blank=True,
                                             help_text="Primary brand colour hex, e.g. #3a5a1e. Overrides theme.")
    site_secondary_color = models.CharField(max_length=20, blank=True,
                                             help_text="Secondary / accent colour hex, e.g. #b88620.")
    site_bg_color        = models.CharField(max_length=20, blank=True,
                                             help_text="Page background colour hex.")
    site_text_color      = models.CharField(max_length=20, blank=True,
                                             help_text="Body text colour hex.")
    site_nav_bg          = models.CharField(max_length=20, blank=True,
                                             help_text="Navbar background colour hex (scrolled state).")
    site_footer_bg       = models.CharField(max_length=20, blank=True,
                                             help_text="Footer background colour hex.")
    site_section_alt_bg  = models.CharField(max_length=20, blank=True,
                                             help_text="Alternating section background colour hex.")
    hero_overlay_opacity = models.FloatField(
        default=0.0, blank=True,
        help_text="Dark overlay opacity on hero image (0.0 = none, 0.6 = strong). Only applies when hero_image is set."
    )

    # Font family
    FONT_CHOICES = [
        # ── Clean & Professional ──
        ("dm_sans",      "DM Sans + DM Serif Display — Clean, modern (default)"),
        ("inter",        "Inter + Playfair Display — Sharp, editorial"),
        ("poppins",      "Poppins + Cormorant Garamond — Friendly, elegant"),
        # ── Classic & Readable ──
        ("raleway",      "Raleway + Lora — Geometric, literary"),
        ("opensans",     "Open Sans + Source Serif 4 — Highly readable, corporate"),
        ("nunito",       "Nunito + Libre Baskerville — Approachable, trustworthy"),
        # ── Bold & Distinctive ──
        ("montserrat",   "Montserrat + Merriweather — Strong headlines, editorial body"),
        ("outfit",       "Outfit + Fraunces — Contemporary, distinctive"),
        ("josefin",      "Josefin Sans + Spectral — Geometric, authoritative"),
        # ── Warm & Expressive ──
        ("quicksand",    "Quicksand + Crimson Pro — Soft, welcoming"),
        ("figtree",      "Figtree + Bitter — Balanced, professional"),
        ("manrope",      "Manrope + Libre Baskerville — Modern, versatile"),
        # ── Premium ──
        ("plus_jakarta",  "Plus Jakarta Sans + Playfair Display — Premium, polished"),
        ("cabinet",      "Cabinet Grotesk + Lora — Bold, confident"),
        ("space_grotesk", "Space Grotesk + Fraunces — Techy, high-impact"),
    ]
    site_font         = models.CharField(max_length=30, choices=FONT_CHOICES, default="dm_sans",
                                          help_text="Font pairing used across the public website.")

    # Hero page-specific images
    about_hero_image  = models.ImageField(upload_to="company/website/", blank=True,
                                           help_text="Hero banner image for the About page.")
    services_hero_image = models.ImageField(upload_to="company/website/", blank=True,
                                             help_text="Hero banner image for the Services/Loans page.")
    team_hero_image   = models.ImageField(upload_to="company/website/", blank=True,
                                           help_text="Hero banner image for the Team page.")
    contact_hero_image = models.ImageField(upload_to="company/website/", blank=True,
                                            help_text="Hero banner image for the Contact page.")

    # Contact page
    contact_intro     = models.TextField(blank=True,
                                          help_text="Introductory text shown at the top of the Contact page.")
    maps_embed_url    = models.URLField(blank=True, max_length=1000,
                                         help_text="Google Maps embed URL for the head office (iFrame src).")

    # ── Appearance ────────────────────────────────────────────

    color_theme     = models.CharField(max_length=20, choices=THEME_CHOICES, default="forest",
                                       help_text="Pre-built colour theme applied across the interface.")

    # ── Website v2: Hero layout ───────────────────────────────
    HERO_LAYOUT_CHOICES = [
        ("split",      "Split — Text left, card right"),
        ("centered",   "Centered — Full-width headline"),
        ("fullscreen", "Full Screen — Image fills viewport"),
    ]
    hero_layout = models.CharField(max_length=20, choices=HERO_LAYOUT_CHOICES, default="split",
                                   help_text="Visual layout of the homepage hero section.")

    # ── Hero carousel ─────────────────────────────────────────
    show_hero_carousel = models.BooleanField(
        default=False,
        help_text="Replace the static hero with an auto-advancing 3-slide carousel.",
    )
    hero_slides = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Up to 3 slide objects: '
            '[{"headline":"...","subheadline":"...","cta_text":"Apply","cta_url":"","overlay":"0.65"}]'
        ),
    )
    hero_slide_2_image = models.ImageField(
        upload_to="company/website/carousel/", blank=True,
        help_text="Background image for carousel slide 2.",
    )
    hero_slide_3_image = models.ImageField(
        upload_to="company/website/carousel/", blank=True,
        help_text="Background image for carousel slide 3.",
    )
    hero_slide_1_feature_image = models.ImageField(
        upload_to="company/website/carousel/feature/", blank=True,
        help_text="Foreground image shown beside the text on carousel slide 1.",
    )
    hero_slide_2_feature_image = models.ImageField(
        upload_to="company/website/carousel/feature/", blank=True,
        help_text="Foreground image shown beside the text on carousel slide 2.",
    )
    hero_slide_3_feature_image = models.ImageField(
        upload_to="company/website/carousel/feature/", blank=True,
        help_text="Foreground image shown beside the text on carousel slide 3.",
    )

    # ── Business identity extras ──────────────────────────────
    founded_year        = models.PositiveSmallIntegerField(null=True, blank=True,
                                                           help_text="Year the company was founded (shown in About stats).")
    license_number      = models.CharField(max_length=80, blank=True,
                                           help_text="Regulatory licence number (shown as a trust signal).")
    registration_number = models.CharField(max_length=80, blank=True,
                                           help_text="Business registration number.")

    # ── SEO ───────────────────────────────────────────────────
    meta_title       = models.CharField(max_length=120, blank=True,
                                        help_text="Browser tab / search engine title (defaults to company name if blank).")
    meta_description = models.TextField(blank=True,
                                        help_text="Meta description for search engines (150–160 characters recommended).")

    # ── Configurable content sections (JSON) ─────────────────
    core_values = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Company values shown on About & Team pages. '
            'JSON: [{"icon":"🤝","title":"Integrity","description":"We..."}]'
        ),
    )
    how_steps = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Steps shown in "How It Works". '
            'JSON: [{"icon":"📋","title":"Register","description":"Visit us..."}]'
        ),
    )
    partners = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Partner / sponsor logos shown as a trust strip. '
            'JSON: [{"name":"Acme Bank","website":"https://..."}]'
        ),
    )
    certifications = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Certifications & memberships. '
            'JSON: [{"icon":"🏅","name":"Microfinance Association","year":2019}]'
        ),
    )
    awards = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Awards & recognition. '
            'JSON: [{"title":"Best MFI 2023","issuer":"Finance Awards Ghana","year":2023}]'
        ),
    )
    business_hours = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Office hours shown on Contact page. '
            'JSON: [{"day":"Monday","open":"8:00 AM","close":"5:00 PM","closed":false}]'
        ),
    )

    # ── Page-specific headlines ───────────────────────────────
    about_headline      = models.CharField(max_length=160, blank=True,
                                           help_text="H1 for the About page (defaults to 'About {company}').")
    about_subheadline   = models.TextField(blank=True,
                                           help_text="Subtext under the About page headline.")
    services_headline   = models.CharField(max_length=160, blank=True,
                                           help_text="H1 for the Services / Loans page.")
    services_subheadline = models.TextField(blank=True,
                                             help_text="Subtext under the Services headline.")
    team_headline       = models.CharField(max_length=160, blank=True,
                                           help_text="H1 for the Team page.")
    team_subheadline    = models.TextField(blank=True,
                                           help_text="Subtext under the Team headline.")
    contact_headline    = models.CharField(max_length=160, blank=True,
                                           help_text="H1 for the Contact page.")
    contact_subheadline = models.TextField(blank=True,
                                           help_text="Subtext under the Contact headline.")

    # ── Homepage CTA section ──────────────────────────────────
    cta_headline    = models.CharField(max_length=180, blank=True,
                                       help_text="Headline for the homepage bottom CTA section.")
    cta_body        = models.TextField(blank=True,
                                       help_text="Body text for the homepage CTA section.")
    cta_button_text = models.CharField(max_length=60, blank=True, default="Contact Us Today",
                                       help_text="Button text in the homepage CTA section.")

    # ── Section visibility toggles ────────────────────────────
    show_stats_band           = models.BooleanField(default=True,
                                                     help_text="Show the stats strip (clients, years, disbursed) on the homepage.")
    show_how_section          = models.BooleanField(default=True,
                                                     help_text="Show the 'How It Works' process section.")
    show_trust_strip          = models.BooleanField(default=True,
                                                     help_text="Show the 4-item trust-signals bar below the hero section.")
    show_partners_section     = models.BooleanField(default=False,
                                                     help_text="Show the Partners / Sponsors logo strip.")
    show_certifications_section = models.BooleanField(default=False,
                                                       help_text="Show the Certifications & Memberships section.")
    show_awards_section       = models.BooleanField(default=False,
                                                     help_text="Show the Awards & Recognition section.")
    show_gallery_section      = models.BooleanField(default=True,
                                                     help_text="Show the gallery section on the About page.")
    show_agents_on_team       = models.BooleanField(default=True,
                                                     help_text="Show field agents on the Team page.")
    show_topbar               = models.BooleanField(default=True,
                                                     help_text="Show the top info bar (phone, email, socials) above the navbar.")

    # ── Tenant messaging & channel integrations ──────────────
    tenant_email_from_address = models.EmailField(
        blank=True,
        help_text="Tenant-specific sender address for operational emails. Falls back to the platform default when blank.",
    )
    tenant_email_host = models.CharField(
        max_length=255,
        blank=True,
        help_text="SMTP host for this tenant's outbound email.",
    )
    tenant_email_port = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="SMTP port for this tenant's outbound email.",
    )
    tenant_email_host_user = models.CharField(
        max_length=255,
        blank=True,
        help_text="SMTP username for this tenant's outbound email.",
    )
    tenant_email_host_password = models.CharField(
        max_length=255,
        blank=True,
        help_text="SMTP password or API secret for this tenant's outbound email.",
    )
    tenant_email_use_tls = models.BooleanField(
        null=True,
        blank=True,
        help_text="Use TLS for this tenant's outbound email. Leave blank to inherit the platform default.",
    )
    tenant_email_use_ssl = models.BooleanField(
        null=True,
        blank=True,
        help_text="Use SSL for this tenant's outbound email. Leave blank to inherit the platform default.",
    )
    tenant_sms_provider = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="SMS provider for this tenant. Arkesel is currently supported in-app.",
    )
    tenant_sms_api_key = models.CharField(
        max_length=255,
        blank=True,
        help_text="Tenant-specific SMS API key.",
    )
    tenant_sms_sender_id = models.CharField(
        max_length=60,
        blank=True,
        help_text="Tenant-specific SMS sender ID.",
    )
    tenant_sms_base_url = models.URLField(
        blank=True,
        help_text="Tenant-specific SMS API base URL.",
    )
    tenant_ussd_provider = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="USSD provider for this tenant, e.g. Hubtel or Arkesel.",
    )
    tenant_ussd_api_key = models.CharField(
        max_length=255,
        blank=True,
        help_text="Tenant-specific USSD API key.",
    )
    tenant_ussd_shortcode = models.CharField(
        max_length=60,
        blank=True,
        help_text="Tenant-specific USSD shortcode or service code.",
    )
    tenant_ussd_username = models.CharField(
        max_length=120,
        blank=True,
        help_text="Tenant-specific USSD account username or client ID.",
    )
    tenant_ussd_callback_token = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional token used to validate inbound USSD callbacks for this tenant.",
    )

    # ── Timestamps ────────────────────────────────────────────
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Company Profile"
        verbose_name_plural = "Company Profile"

    @property
    def gallery_items(self):
        """Return list of (image, caption) tuples for non-blank gallery slots."""
        items = []
        for i in range(1, 11):
            img = getattr(self, f"gallery_image_{i}", None)
            cap = getattr(self, f"gallery_caption_{i}", "") or ""
            if img:
                items.append({"image": img, "caption": cap, "index": i})
        return items

    @staticmethod
    def _hex_adjust(hex_color: str, factor: float) -> str:
        """Return a lightened (factor>1) or darkened (factor<1) hex colour."""
        hex_color = hex_color.lstrip("#")
        if len(hex_color) != 6:
            return "#" + hex_color
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        r = min(255, max(0, int(r * factor)))
        g = min(255, max(0, int(g * factor)))
        b = min(255, max(0, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"

    @property
    def css_overrides(self):
        """Build CSS variable overrides from site branding fields."""
        rules = []
        if self.site_primary_color:
            p = self.site_primary_color
            rules.append(f"--primary:{p};")
            rules.append(f"--primary-l:{self._hex_adjust(p, 1.25)};")
            rules.append(f"--primary-xl:{self._hex_adjust(p, 1.50)};")
            rules.append(f"--primary-d:{self._hex_adjust(p, 0.78)};")
            # Derived transparent variants
            rules.append(f"--pg:color-mix(in srgb,{p} 16%,transparent);")
        if self.site_secondary_color:
            s = self.site_secondary_color
            rules.append(f"--accent:{s};")
            rules.append(f"--accent-2:{s};")
            rules.append(f"--gold:{s};")
            rules.append(f"--gold-d:{self._hex_adjust(s, 0.82)};")
            rules.append(f"--gold-pale:color-mix(in srgb,{s} 10%,transparent);")
            rules.append(f"--gold-glow:color-mix(in srgb,{s} 18%,transparent);")
        if self.site_bg_color:
            rules.append(f"--paper:{self.site_bg_color};")
            rules.append(f"--bg:{self.site_bg_color};")
        if self.site_text_color:
            rules.append(f"--text:{self.site_text_color};")
        if self.site_nav_bg:
            rules.append(f"--surface:{self.site_nav_bg};")
            rules.append(f"--nav-bg:{self.site_nav_bg};")
        if self.site_footer_bg:
            rules.append(f"--footer:{self.site_footer_bg};")
            rules.append(f"--footer-bg:{self.site_footer_bg};")
        if self.site_section_alt_bg:
            rules.append(f"--soft:{self.site_section_alt_bg};")
            rules.append(f"--alt-bg:{self.site_section_alt_bg};")
        return " ".join(rules)

    # Font data: (body_family, serif_family, google_fonts_url)
    _FONT_DATA = {
        "dm_sans": (
            "'DM Sans'", "'DM Serif Display'",
            "https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@400;500;600;700;800&display=swap",
        ),
        "inter": (
            "'Inter'", "'Playfair Display'",
            "https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,500;0,700;1,400&family=Inter:wght@400;500;600;700&display=swap",
        ),
        "poppins": (
            "'Poppins'", "'Cormorant Garamond'",
            "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Poppins:wght@400;500;600;700&display=swap",
        ),
        "raleway": (
            "'Raleway'", "'Lora'",
            "https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;1,400&family=Raleway:wght@400;500;600;700;800&display=swap",
        ),
        "opensans": (
            "'Open Sans'", "'Source Serif 4'",
            "https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,wght@0,400;0,600;1,400&family=Open+Sans:wght@400;500;600;700&display=swap",
        ),
        "nunito": (
            "'Nunito'", "'Libre Baskerville'",
            "https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Nunito:wght@400;500;600;700;800&display=swap",
        ),
        "montserrat": (
            "'Montserrat'", "'Merriweather'",
            "https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,400;0,700;1,400&family=Montserrat:wght@400;500;600;700;800&display=swap",
        ),
        "outfit": (
            "'Outfit'", "'Fraunces'",
            "https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Outfit:wght@400;500;600;700;800&display=swap",
        ),
        "josefin": (
            "'Josefin Sans'", "'Spectral'",
            "https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,600;1,400&family=Josefin+Sans:wght@400;500;600;700&display=swap",
        ),
        "quicksand": (
            "'Quicksand'", "'Crimson Pro'",
            "https://fonts.googleapis.com/css2?family=Crimson+Pro:ital,wght@0,400;0,600;1,400&family=Quicksand:wght@400;500;600;700&display=swap",
        ),
        "figtree": (
            "'Figtree'", "'Bitter'",
            "https://fonts.googleapis.com/css2?family=Bitter:ital,wght@0,400;0,600;1,400&family=Figtree:wght@400;500;600;700;800&display=swap",
        ),
        "manrope": (
            "'Manrope'", "'Libre Baskerville'",
            "https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Manrope:wght@400;500;600;700;800&display=swap",
        ),
        "plus_jakarta": (
            "'Plus Jakarta Sans'", "'Playfair Display'",
            "https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,500;0,700;1,400&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap",
        ),
        "cabinet": (
            "'Cabinet Grotesk'", "'Lora'",
            "https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;1,400&family=Cabinet+Grotesk:wght@400;500;700;800&display=swap",
        ),
        "space_grotesk": (
            "'Space Grotesk'", "'Fraunces'",
            "https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Space+Grotesk:wght@400;500;600;700&display=swap",
        ),
    }

    @property
    def font_urls(self):
        """Return Google Fonts URL for the selected font pair."""
        data = self._FONT_DATA.get(self.site_font or "dm_sans", self._FONT_DATA["dm_sans"])
        return data[2]

    @property
    def font_body_family(self):
        data = self._FONT_DATA.get(self.site_font or "dm_sans", self._FONT_DATA["dm_sans"])
        return data[0]

    @property
    def font_serif_family(self):
        data = self._FONT_DATA.get(self.site_font or "dm_sans", self._FONT_DATA["dm_sans"])
        return data[1]

    @property
    def dashboard_css_overrides(self):
        """CSS variable overrides for the internal dashboard (templates/base.html naming)."""
        rules = []
        if self.site_primary_color:
            p = self.site_primary_color
            rules.append(f"--primary:{p};")
            rules.append(f"--primary-2:{self._hex_adjust(p, 0.78)};")
            rules.append(f"--primary-3:{self._hex_adjust(p, 1.28)};")
            rules.append(f"--primary-glow:color-mix(in srgb,{p} 16%,transparent);")
            rules.append(f"--body-bg-a:color-mix(in srgb,{p} 10%,transparent);")
            rules.append(f"--border-accent:color-mix(in srgb,{p} 20%,transparent);")
        if self.site_secondary_color:
            s = self.site_secondary_color
            rules.append(f"--gold:{s};")
            rules.append(f"--gold-2:{self._hex_adjust(s, 0.82)};")
            rules.append(f"--gold-pale:color-mix(in srgb,{s} 10%,transparent);")
            rules.append(f"--gold-glow:color-mix(in srgb,{s} 16%,transparent);")
            rules.append(f"--body-bg-b:color-mix(in srgb,{s} 7%,transparent);")
        if self.site_bg_color:
            rules.append(f"--bg:{self.site_bg_color};")
        if self.site_text_color:
            rules.append(f"--text:{self.site_text_color};")
        return " ".join(rules)

    def __str__(self):
        return self.company_name

    # ── Singleton helper ──────────────────────────────────────
    @classmethod
    def get_solo(cls):
        """
        Return the single CompanyProfile instance, creating it with
        sensible defaults if it doesn't exist yet.
        """
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "loan_tiers": DEFAULT_LOAN_TIERS_JSON,
                "borrower_languages": ["Twi", "Ewe", "Ga", "Hausa"],
                "payroll_tax_brackets": default_payroll_tax_brackets(),
            },
        )
        return obj

    # ── Convenience properties ────────────────────────────────
    @property
    def formatted_currency(self):
        return self.currency_symbol or self.currency_code

    @property
    def tiers_for_template(self):
        """Return loan_tiers, falling back to defaults if empty."""
        return self.loan_tiers or DEFAULT_LOAN_TIERS_JSON

    @property
    def languages_for_template(self):
        return self.borrower_languages or ["Twi", "Ewe", "Ga", "Hausa"]

    @property
    def payroll_tax_brackets_for_template(self):
        return self.payroll_tax_brackets or default_payroll_tax_brackets()

    @property
    def repayment_unit(self):
        return {
            "weekly":   "week",
            "biweekly": "fortnight",
            "monthly":  "month",
        }.get(self.repayment_cycle, "period")

    def format_amount(self, value) -> str:
        """Format a Decimal/float as currency string using this company's symbol."""
        try:
            d = Decimal(str(value))
            return f"{self.formatted_currency} {d:,.2f}"
        except Exception:
            return str(value)


class CompanyDocument(models.Model):
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="company/documents/")
    is_public = models.BooleanField(
        default=True,
        help_text="Show this document on the public website downloads page.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "title", "id"]

    def __str__(self):
        return self.title
