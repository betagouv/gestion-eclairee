import csv
import logging
import optparse
import os
import platform
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from django.core.files.storage import default_storage

from cloakbrowser import launch_context
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

# Determine select-all keyboard shortcut based on OS
SELECT_ALL_MODIFIER = "Meta" if platform.system() == "Darwin" else "Control"


@dataclass
class SearchParams:
    """Parameters for searching invoices on CPRO."""

    service: Optional[str] = None
    provider: Optional[str] = None
    num_ej: Optional[str] = None
    facture_num: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    ignore_payment_state: Optional[bool] = None

    def to_log_string(self) -> str:
        """Convert search params to a formatted string for logging.

        Returns:
            A string like "[service=ABC, provider=123456789]" or empty string if no params
        """
        parts = []
        if self.service:
            parts.append(f"service={self.service}")
        if self.provider:
            parts.append(f"provider={self.provider}")
        if self.num_ej:
            parts.append(f"num_ej={self.num_ej}")
        if self.facture_num:
            parts.append(f"facture_num={self.facture_num}")
        if self.ignore_payment_state:
            parts.append(f"ignore_payment_state={self.ignore_payment_state}")
        if self.start_date:
            parts.append(f"start_date={self.start_date}")
        if self.end_date:
            parts.append(f"end_date={self.end_date}")
        return f"[{', '.join(parts)}]" if parts else ""


def parse_args():
    parser = optparse.OptionParser()
    parser.add_option("--start", dest="start", help="Start date in ISO format (YYYY-MM-DD)")
    parser.add_option("--end", dest="end", help="End date in ISO format (YYYY-MM-DD)")
    parser.add_option("--service", dest="service", help="Service code")
    parser.add_option("--headed", action="store_true", default=False, help="Run in headed mode")
    parser.add_option(
        "--provider",
        dest="provider",
        help="Provider identifier (SIREN=9 digits or SIRET=14 digits)",
    )
    parser.add_option("--num-ej", dest="num_ej", help="Numéro EJ (Bon de commande)")
    parser.add_option("--facture-num", dest="facture_num", help="Numéro de facture")
    parser.add_option(
        "--input-file",
        dest="input_file",
        help=(
            "Input file containing EJ, SERVICES, and FACTURE_NUM columns (space-separated services). "
            "Not compatible with --service, --num-ej, or --facture-num"
        ),
    )
    parser.add_option(
        "--ignore-payment-state",
        dest="ignore_payment_state",
        action="store_true",
        default=False,
        help="Ignore payment state",
    )
    parser.add_option(
        "--log-dir",
        dest="log_dir",
        help="Directory to save log files (format: log_yyyymmdd_hhmmss.txt)",
    )
    parser.add_option(
        "--skip-tuples",
        dest="skip_tuples",
        type="int",
        default=0,
        help="Number of initial tuples to skip (for resuming interrupted processing)",
    )
    options, args = parser.parse_args()
    return options


def init_context(headless: bool = True):
    """Initialize browser context with cookies and download handler."""
    logger.info("Initializing context...")
    ctx = launch_context(headless=headless, locale="fr-FR")
    ctx.add_cookies(
        [
            {
                "name": "JSESSIONID",
                "value": os.environ["JSESSIONID"],
                "domain": "cpro.chorus-pro.gouv.fr",
                "path": "/cpp",
            },
        ]
    )
    page = ctx.new_page()
    logger.info("Context initialized.")
    return ctx, page


def init_search_page(page, ignore_payment_state: bool):
    """Navigate to the invoice search page and fill the static form criteria."""
    logger.info("Initializing search page")

    # Ouverture de la page
    page.goto("https://cpro.chorus-pro.gouv.fr/cpp/rechercheFactures")

    if not ignore_payment_state:
        # Sélection de l'état Mise en paiement
        page.select_option("select[name='listeResultats.critere.etatCourant']", value="MISE_EN_PAIEMENT")

    logger.info("Search page initialized.")


def open_advanced_search_section(page):
    expander = page.locator("[data-target='#GDP_RechercheFacture_CriteresPanneau_Body']")
    is_expanded = expander.get_attribute("aria-expanded") == "true"
    if not is_expanded:
        expander.click()
    page.locator("#GFR_RechercheFactureEtatAcompteRecus_Criteres_BoutonRechercher").scroll_into_view_if_needed()


def fill_service(page, service: str):
    # Selection du service
    page.select_option("select[name='listeResultats.critere.structureDestinataireId']", value="568055")
    page.click("#GFR_RechercheFacturesRecues_Criteres_BtnRechercherService")
    page.fill("input[name='listeServices.critere.code']", service)
    page.click("button[type='submit']")
    page.click("#selection0")


def fill_provider(page, provider: str):
    """Fill the provider search field.

    Args:
        page: The Playwright page object
        provider: The provider identifier (SIREN=9 digits or SIRET=14 digits)
    """
    if not provider:
        raise ValueError("Must provide a provider identifier (SIREN or SIRET).")

    # Determine if it's SIREN (9 digits) or SIRET (14 digits)
    provider = provider.strip()
    is_siren = len(provider) == 9
    is_siret = len(provider) == 14

    if not (is_siren or is_siret):
        raise ValueError(
            f"Provider identifier must be 9 digits (SIREN) or 14 digits (SIRET), got {len(provider)} digits: {provider}"
        )

    logger.info(f"Filling provider: identifier={provider}, type={'SIREN' if is_siren else 'SIRET'}")

    # Click on the provider select2 container to open the dropdown
    page.click(
        "#select2-GFR_RechercheFacturesRecues_Criteres_StructureFournisseurGFR_RechercheFacturesRecues-container"
    )

    # Type the identifier
    page.keyboard.type(provider)

    # Wait for results and click the first one
    page.click(
        "#select2-GFR_RechercheFacturesRecues_Criteres_StructureFournisseurGFR_RechercheFacturesRecues-results "
        "li:first-child"
    )

    # If SIREN, check if SIREN checkbox is disabled and enable it if needed
    if is_siren:
        siren_checkbox = page.locator("#TRA_Recherche_Factures_Coche_SIREN")
        is_disabled = siren_checkbox.get_attribute("disabled")
        if is_disabled:
            logger.info("SIREN checkbox is disabled, enabling it...")
            page.evaluate("""() => {
                const el = document.getElementById('TRA_Recherche_Factures_Coche_SIREN');
                if (el) el.disabled = false;
            }""")
        # Click the label to select SIREN
        page.click("label[for='TRA_Recherche_Factures_Coche_SIREN']")

        # Assert that SIREN checkbox is checked
        assert page.locator("#TRA_Recherche_Factures_Coche_SIREN").is_checked(), "SIREN checkbox should be checked"
        assert page.input_value("input[name='rechercheParSiren']") == "true", "rechercheParSiren should be true"

    logger.info(f"Provider filled successfully: {provider}")


def fill_num_ej(page, num_ej: str):
    """Fill the numéro bon de commande (EJ) field.

    Args:
        page: The Playwright page object
        num_ej: The numéro EJ (bon de commande) to fill
    """
    logger.info(f"Filling numéro EJ: {num_ej}")
    open_advanced_search_section(page)
    page.fill("input[name='listeResultats.critere.numeroBonDeCommande']", num_ej)
    logger.info(f"Numéro EJ filled successfully: {num_ej}")


def fill_facture_num(page, facture_num: str):
    """Fill the `Numéro de facture` field."""
    logger.info(f"Filling 'Numéro de facture': {facture_num}")
    open_advanced_search_section(page)
    page.fill("input[name='listeResultats.critere.numero']", facture_num)
    logger.info(f"'Numéro de facture' filled successfully: {facture_num}")


def fill_date_range(page, start_date: date, end_date: date):
    """Fill the date range fields with start and end dates.

    Args:
        page: The Playwright page object
        start_date: The start date to fill in the start field
        end_date: The end date to fill in the end field
    """
    open_advanced_search_section(page)
    str_start = start_date.strftime("%d/%m/%Y")
    str_end = end_date.strftime("%d/%m/%Y")
    logger.info(f"Filling date range: {start_date} to {end_date}")
    page.click("input[name='listeResultats.critere.dateHeureEtatCourantDebut']")
    page.keyboard.press(f"{SELECT_ALL_MODIFIER}+a")
    page.keyboard.type(str_start)
    page.click("input[name='listeResultats.critere.dateHeureEtatCourantFin']")
    page.keyboard.press(f"{SELECT_ALL_MODIFIER}+a")
    page.keyboard.type(str_end)


def submit_form(page) -> bool:
    """Submit the search form by clicking the search button.
    Returns True if results were found, False otherwise.

    Args:
        page: The Playwright page object
    """
    logger.info("Submitting search form...")
    page.click("#GFR_RechercheFactureEtatAcompteRecus_Criteres_BoutonRechercher")
    page.wait_for_load_state("load")
    logger.info("Search form submitted.")

    # Check if table with "Résultats de la recherche" caption exists (indicates results were found)
    if page.query_selector("table caption:has-text('Résultats de la recherche')") is None:
        logger.info("No results found.")
        return False
    return True


def check_form_arguments(page, start_date: date, end_date: date):
    """Verify that the form fields have the expected values.

    Args:
        page: The Playwright page object
        str_date: The date string in DD/MM/YYYY format
    """
    str_start = start_date.strftime("%d/%m/%Y")
    str_end = end_date.strftime("%d/%m/%Y")
    assert page.input_value("input[name='listeResultats.critere.dateHeureEtatCourantDebut']") == str_start
    assert page.input_value("input[name='listeResultats.critere.dateHeureEtatCourantFin']") == str_end


def go_next_page(page) -> bool:
    """Check for a next page button and click it if available.

    Returns True if a new page was loaded, False otherwise.
    """
    next_button = page.locator("button[title='Aller à la page suivante du tableau']")
    is_disabled = next_button.get_attribute("disabled")
    if is_disabled:
        logger.info("No next page available.")
        return False

    logger.info("Navigating to next page...")
    next_button.click()
    page.wait_for_load_state("load")
    page_number = get_current_page_number(page)
    logger.info("Next page loaded (%s).", page_number)
    return True


def get_current_page_number(page):
    page_button = page.locator("li.paginate__page.paginate__page_active button[name='listeResultats.page']")
    page_number = page_button.get_attribute("value")
    return page_number


def verify_download_integrity(filepath: str, id_cpro: str | None) -> bool:
    """Verify that a downloaded zip file is not corrupted by checking IdCPRO in PivotS.xml.

    Opens the zip file, finds PivotS.xml inside, and reads it until finding
    the IdCPRO value by searching for <IdCPRO> and </IdCPRO> markers.
    The expected id_chorus is extracted from the filename (facture_<idchorus>.zip).

    Args:
        filepath: Path to the downloaded zip file
        id_cpro (optional): Expected id cpro, default: extracted from filename

    Returns:
        True if the IdCPRO matches the id_chorus from filename, False otherwise
    """
    # Extract id chorus from filename (facture_<idchorus>.zip)
    filename = os.path.split(filepath)[-1]
    if id_cpro:
        expected_id_chorus = id_cpro
    else:
        expected_id_chorus = os.path.splitext(filename)[0].split("_")[-1]
    try:
        with zipfile.ZipFile(filepath, "r") as zip_ref:
            # Find PivotS.xml in the zip
            pivot_file = None
            for filename in zip_ref.namelist():
                if filename.endswith("PivotS.xml"):
                    pivot_file = filename
                    break

            if pivot_file is None:
                logger.error(f"PivotS.xml not found in {filepath}")
                return False

            # Read PivotS.xml in text mode and search for IdCPRO
            with zip_ref.open(pivot_file) as xml_file:
                # Read in chunks until we find </IdCPRO>
                chunk_size = 8192
                buffer = ""
                start_marker = "<IdCPRO>"
                end_marker = "</IdCPRO>"

                while True:
                    chunk = xml_file.read(chunk_size)
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="ignore")

                    # Check if we have the end marker
                    if end_marker in buffer:
                        break

                # Find IdCPRO tags in buffer
                start_idx = buffer.find(start_marker)

                if start_idx == -1:
                    logger.error(f"IdCPRO start tag not found in PivotS.xml in {filepath}")
                    return False

                start_idx += len(start_marker)
                end_idx = buffer.find(end_marker, start_idx)

                if end_idx == -1:
                    logger.error(f"IdCPRO end tag not found in PivotS.xml in {filepath}")
                    return False

                actual_idcpro = buffer[start_idx:end_idx]

                if actual_idcpro != expected_id_chorus:
                    logger.error(f"IdCPRO mismatch in {filepath}: expected {expected_id_chorus}, got {actual_idcpro}")
                    return False

                logger.debug(f"IdCPRO verification passed for {filepath}: {actual_idcpro}")
                return True

    except zipfile.BadZipFile:
        logger.error(f"File {filepath} is not a valid zip file")
        return False


def download_items(page, params: Optional[SearchParams] = None):
    """Download items one by one from the current page.

    Iterates over all buttons with name='Synthese_Btn_TelechargerUnitaire',
    extracts the data-value attribute (id_chorus), clicks the button,
    and saves the download as facture_<id_chorus>.zip.

    Args:
        page: The Playwright page object
        params: Optional SearchParams for additional logging context
    """
    # Find all individual download buttons
    download_buttons = page.locator("button[name='Synthese_Btn_TelechargerUnitaire']")

    # Get the count of buttons
    button_count = download_buttons.count()

    # Get params string for warning/error logging only
    params_str = params.to_log_string() if params else ""

    logger.info(f"Found {button_count} items to download individually")

    stats = {"files": button_count, "download": 0, "skip": 0, "error": 0}
    # Iterate over each button
    for i in range(button_count):
        # Get the i-th button
        button = download_buttons.nth(i)

        # Get the data-value attribute which contains the id_chorus
        id_chorus = button.get_attribute("data-value")
        if not id_chorus:
            logger.warning(f"Button {i} has no data-value attribute, skipping {params_str}")
            stats["error"] += 1
            continue

        filename = f"facture_{id_chorus}.zip"
        filepath = f"cpro/factures/{filename}"

        if default_storage.exists(filepath):
            logger.info(f"File {filename} already exists, skipping download for id_chorus={id_chorus}")
            stats["skip"] += 1
            continue

        logger.info(f"Downloading item {i + 1}/{button_count} with id_chorus={id_chorus}")

        # Click the button to trigger download with retry logic (3 attempts max)
        download_success = False
        for attempt in range(3):
            try:
                button.click()
                with page.expect_download(timeout=30 * 1000) as download_info:
                    page.click("#GDP_Telechargementfacture_BoutonTelecharger")

                download = download_info.value
                assert download_info.is_done(), "Download should be done."
                download_path = download.path()

                # Verify download integrity
                if not verify_download_integrity(download_path, id_cpro=id_chorus):
                    logger.warning(f"Download verification failed for {filename} {params_str}")

                # Save file
                with open(download_path, "rb") as src:
                    default_storage.save(filepath, src)
                logger.info(f"Saved as {filename}")
                download_success = True
                break
            except PlaywrightTimeoutError as e:
                logger.warning(f"Download attempt {attempt + 1}/3 failed for {filename}: {e} {params_str}")
                if attempt < 2:
                    logger.info(f"Retrying download for {filename}...")
                else:
                    logger.error(f"Max retries reached for download_items, skipping {params_str} filename={filename}")

        if not download_success:
            stats["error"] += 1
            continue

        stats["download"] += 1

    return stats


def read_input_file(input_file: str) -> list[tuple[str, str, str]]:
    """Read input file with EJ, SERVICES and FACTURE_NUM columns.

    Args:
        input_file: Path to the input file (CSV format expected)

    Returns:
        List of tuples (ej, service, facture_num) extracted from the file
    """
    logger.info(f"Reading input file: {input_file}")

    tuples = []
    with open(input_file, "r", newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)

        # Check required columns exist
        if "EJ" not in reader.fieldnames:
            raise ValueError(f"Input file must contain 'EJ' column. Available columns: {reader.fieldnames}")
        if "SERVICES" not in reader.fieldnames:
            raise ValueError(f"Input file must contain 'SERVICES' column. Available columns: {reader.fieldnames}")

        for row in reader:
            ej = row["EJ"].strip()
            services_str = row["SERVICES"].strip()
            facture_num = row.get("FACTURE_NUM", "").strip()

            # assert ej, f"row with empty EJ: {row}"
            assert not ej or len(ej) == 10, f"row with invalid EJ: {row}"
            # assert services_str, f"Row with empty SERVICES: {row}"

            if len(facture_num) < 3:
                logger.warning("Facture num too short: %r.", row)
                facture_num = ""

            if not services_str.strip():
                tuples.append((ej, None, facture_num))
            else:
                # Split services by space
                services = services_str.strip().split()

                # Create a tuple for each service
                for service in services:
                    service = service.strip()
                    if service and service not in ("WFBATCH", "AIFEMNT093"):
                        tuples.append((ej, service, facture_num))
                        logger.debug(f"Added tuple: EJ={ej}, Service={service}, Facture={facture_num}")

    logger.info(f"Extracted {len(tuples)} (EJ, service, facture_num) tuples from input file")
    return tuples


def build_export_filename(params: SearchParams) -> str:
    """Build export CSV filename based on search parameters.

    Format: cpro/exports/<facture_num>_<num_ej>_<service>_<provider>_<start>_<end>.csv

    Args:
        params: SearchParams containing all search criteria

    Returns:
        A filename string with path
    """
    parts = []

    if params.facture_num:
        parts.append(f"FACTURE_{params.facture_num}")

    if params.num_ej:
        parts.append(params.num_ej)

    if params.service:
        parts.append(params.service)

    if params.provider:
        parts.append(params.provider)

    if params.ignore_payment_state:
        parts.append("no_payment_state")

    if params.start_date:
        parts.append(params.start_date.strftime("%Y%m%d"))

    if params.end_date:
        parts.append(params.end_date.strftime("%Y%m%d"))

    filename = "_".join(parts) + ".csv"
    return f"cpro/exports/{filename}"


def download_export_csv(page, params: SearchParams) -> str:
    """Download the export CSV file after search.

    Clicks on the export button and saves the result.

    Args:
        page: The Playwright page object
        params: SearchParams containing all search criteria

    Returns:
        The path where the file was saved
    """
    logger.info("Downloading export CSV...")

    # Build filename
    filepath = build_export_filename(params)

    if default_storage.exists(filepath):
        logger.info(f"Export file {filepath} already exists, skipping download")
        return filepath

    # Click the export button and wait for download
    with page.expect_download(timeout=60 * 1000) as download_info:
        page.click("#GFR_RechercheFactureEtatAcompteRecus_Resultats_BoutonExporter")

    download = download_info.value
    assert download_info.is_done(), "Download should be done."
    download_path = download.path()
    with open(download_path, "rb") as src:
        default_storage.save(filepath, src)

    logger.info(f"Export CSV saved as {filepath}")
    return filepath


def search_and_download(page, params: SearchParams):
    """Search for invoices based on the provided parameters and download all results.

    Args:
        page: The Playwright page object
        params: SearchParams containing all search criteria
    """
    logger.info(f"Starting search and download with params: {params}")

    # Initialize search page once
    init_search_page(page, params.ignore_payment_state)

    # Fill service
    if params.service:
        fill_service(page, params.service)

    # Fill provider if specified
    if params.provider:
        fill_provider(page, params.provider)

    # Fill numéro EJ if specified
    if params.num_ej:
        fill_num_ej(page, params.num_ej)

    # Fill facture num if specified
    if params.facture_num:
        fill_facture_num(page, params.facture_num)

    # Fill date range
    if params.start_date and params.end_date:
        fill_date_range(page, params.start_date, params.end_date)

    logger.info(f"Starting download for service={params.service}, num_ej={params.num_ej}, facture={params.facture_num}")
    if not submit_form(page):
        logger.info("No results found.")
        return

    # Download export CSV
    download_export_csv(page, params)

    # Download all pages
    while True:
        stats = download_items(page, params)
        logger.info("Downloads: %s", stats)
        if not go_next_page(page):
            break


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gesec.settings")
    django.setup()

    options = parse_args()

    # Setup logging
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = logging.INFO

    # Create log file handler if --log-dir is specified
    file_handler = None
    if options.log_dir:
        os.makedirs(options.log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"log_{timestamp}.txt"
        log_filepath = os.path.join(options.log_dir, log_filename)
        file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(log_format))
        root_logger = logging.getLogger("")
        root_logger.addHandler(file_handler)

    # Parse optional date range
    start_date = date.fromisoformat(options.start) if options.start else None
    end_date = date.fromisoformat(options.end) if options.end else None

    # Handle input file mode
    use_input_file = options.input_file is not None

    # Validate skip_tuples
    if options.skip_tuples < 0:
        raise ValueError("--skip-tuples must be a non-negative integer")

    # Validate compatibility: --input-file is not compatible with --service or --num-ej
    if use_input_file:
        if options.service:
            raise ValueError(
                "--input-file is not compatible with --service. "
                "Use either --input-file or --service/--num-ej, not both."
            )
        if options.num_ej:
            raise ValueError(
                "--input-file is not compatible with --num-ej. Use either --input-file or --service/--num-ej, not both."
            )
        if options.facture_num:
            raise ValueError(
                "--input-file is not compatible with --facture-num. Use either --input-file or --facture-num, not both."
            )

        # Read tuples from input file
        tuples = read_input_file(options.input_file)
        if not tuples:
            raise ValueError("No valid (EJ, service, facture_num) tuples found in input file.")
    else:
        # Single mode: create a single tuple from provided options
        tuples = [(options.num_ej, options.service, options.facture_num)]

    ctx = None
    try:
        ctx, page = init_context(headless=not options.headed)

        # Process each (num_ej, service, facture_num) tuple
        total_tuples = len(tuples)
        skip_count = options.skip_tuples
        if skip_count > 0:
            logger.info(f"Skipping first {skip_count} tuple(s) as requested")

        for idx, (num_ej, service, facture_num) in enumerate(tuples, 1):
            if idx <= skip_count:
                logger.debug(
                    f"Skipping tuple {idx}/{total_tuples}: EJ={num_ej}, Service={service}, Facture={facture_num}"
                )
                continue

            logger.info(
                f"Processing tuple: EJ={num_ej}, Service={service}, Facture={facture_num} ({idx}/{total_tuples})"
            )

            # Create search parameters for this tuple
            params = SearchParams(
                service=service,
                provider=options.provider,
                num_ej=num_ej,
                facture_num=facture_num,
                start_date=start_date,
                end_date=end_date,
                ignore_payment_state=options.ignore_payment_state,
            )

            # Search and download with retry logic (3 attempts max)
            for attempt in range(3):
                try:
                    start_time = time.perf_counter()
                    search_and_download(page, params)
                    duration = time.perf_counter() - start_time
                    logger.info(
                        f"Processing completed in {duration:.2f}s for EJ={num_ej}, "
                        f"Service={service}, Facture={facture_num} ({idx}/{total_tuples}) {params.to_log_string()}"
                    )
                    break
                except PlaywrightTimeoutError as e:
                    duration = time.perf_counter() - start_time
                    logger.warning(
                        f"search_and_download attempt {attempt + 1}/3 failed in {duration:.2f} "
                        f"for EJ={num_ej}, Service={service}, Facture={facture_num}: {e} {params.to_log_string()}"
                    )
                    if attempt < 2:
                        logger.info("Retrying search_and_download...")
                    else:
                        logger.error(f"Max retries reached for search_and_download, skipping {params.to_log_string()}")

        if options.headed:
            input("Press any key to quit...")
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        if ctx is not None:
            logger.info("Closing context...")
            ctx.close()
            logger.info("Context closed.")
