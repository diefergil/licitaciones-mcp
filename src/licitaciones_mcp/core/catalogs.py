"""Small public catalogs used for normalized tender labels and facets."""

from __future__ import annotations

from licitaciones_mcp.core.models import TenderSource, TenderStatus
from licitaciones_mcp.core.normalization import normalize_text

PLACSP_NOTICE_TYPES: dict[str, str] = {
    "PRE": "Anuncio previo",
    "PUB": "En plazo",
    "EV": "Pendiente de adjudicación",
    "ADJ": "Adjudicada",
    "RES": "Resuelta",
    "ANUL": "Anulada",
    "DES": "Desierta",
}

PLACSP_NOTICE_STATUS: dict[str, TenderStatus] = {
    "PRE": TenderStatus.PLANNED,
    "PUB": TenderStatus.OPEN,
    "EV": TenderStatus.CLOSED,
    "ADJ": TenderStatus.AWARDED,
    "RES": TenderStatus.CLOSED,
    "ANUL": TenderStatus.CANCELLED,
    "DES": TenderStatus.CLOSED,
}

PLACSP_CONTRACT_TYPES: dict[str, str] = {
    "1": "Suministros",
    "2": "Servicios",
    "3": "Obras",
    "21": "Gestión de servicios públicos",
    "22": "Concesión de servicios",
    "31": "Concesión de obras públicas",
    "32": "Concesión de obras",
    "40": "Colaboración público-privada",
    "7": "Administrativo especial",
    "8": "Privado",
    "50": "Patrimonial",
    "999": "Otros",
}

PLACSP_PROCEDURE_TYPES: dict[str, str] = {
    "1": "Abierto",
    "2": "Restringido",
    "3": "Negociado sin publicidad",
    "4": "Negociado con publicidad",
    "5": "Diálogo competitivo",
    "6": "Contrato menor",
    "7": "Derivado de acuerdo marco",
    "8": "Concurso de proyectos",
    "100": "Normas internas",
    "999": "Otros",
}

PLACSP_DATASET_KINDS: dict[str, str] = {
    "licitaciones": "Licitaciones sin menores",
    "agregacion": "Licitaciones agregadas sin menores",
    "menores": "Contratos menores",
    "encargos": "Encargos a medios propios",
    "consultas": "Consultas preliminares de mercado",
}

CPV_SECTORS: dict[str, str] = {
    "03": "Productos agrícolas, ganaderos, pesca y forestales",
    "09": "Derivados del petróleo, combustibles, electricidad y otras energías",
    "14": "Minería, metales básicos y productos afines",
    "15": "Alimentos, bebidas, tabaco y productos afines",
    "16": "Maquinaria agrícola",
    "18": "Ropa, calzado, artículos de viaje y accesorios",
    "19": "Cuero, textiles, plástico y caucho",
    "22": "Impresos y productos relacionados",
    "24": "Productos químicos",
    "30": "Máquinas, equipos y material de oficina e informática",
    "31": "Maquinaria, aparatos y material eléctrico",
    "32": "Equipos de radio, televisión, comunicaciones y telecomunicaciones",
    "33": "Equipos médicos, farmacéuticos y de higiene personal",
    "34": "Equipos de transporte y productos auxiliares",
    "35": "Equipos de seguridad, extinción, policía y defensa",
    "37": "Instrumentos musicales, deporte, juegos y artesanía",
    "38": "Equipos de laboratorio, ópticos y de precisión",
    "39": "Mobiliario, equipamiento doméstico y limpieza",
    "41": "Agua recogida y depurada",
    "42": "Maquinaria industrial",
    "43": "Maquinaria para minería, canteras, construcción y obras públicas",
    "44": "Estructuras, materiales y productos de construcción",
    "45": "Trabajos de construcción",
    "48": "Paquetes de software y sistemas de información",
    "50": "Servicios de reparación y mantenimiento",
    "51": "Servicios de instalación",
    "55": "Hostelería, restauración y comercio al por menor",
    "60": "Servicios de transporte",
    "63": "Servicios complementarios y auxiliares de transporte",
    "64": "Correos y telecomunicaciones",
    "65": "Servicios públicos",
    "66": "Servicios financieros y de seguros",
    "70": "Servicios inmobiliarios",
    "71": "Arquitectura, construcción, ingeniería e inspección",
    "72": "Servicios TI: consultoría, software, internet y apoyo",
    "73": "Investigación y desarrollo",
    "75": "Administración pública, defensa y seguridad social",
    "76": "Servicios relacionados con petróleo y gas",
    "77": "Servicios agrícolas, forestales, hortícolas y acuícolas",
    "79": "Servicios a empresas: derecho, marketing, consultoría y selección",
    "80": "Enseñanza y formación",
    "85": "Salud y asistencia social",
    "90": "Alcantarillado, basura, limpieza y medio ambiente",
    "92": "Servicios recreativos, culturales y deportivos",
    "98": "Otros servicios comunitarios, sociales y personales",
}

STATUS_LABELS: dict[TenderStatus, str] = {
    TenderStatus.PLANNED: "Planificada",
    TenderStatus.OPEN: "Abierta",
    TenderStatus.CLOSED: "Cerrada",
    TenderStatus.AWARDED: "Adjudicada",
    TenderStatus.CANCELLED: "Cancelada",
    TenderStatus.UNKNOWN: "Desconocida",
}


def placsp_notice_label(value: str | None) -> str | None:
    """Return the public label for a PLACSP notice/status code."""

    normalized = _catalog_key(value)
    return PLACSP_NOTICE_TYPES.get(normalized) or normalize_text(value)


def placsp_contract_type_label(value: str | None) -> str | None:
    """Return the public label for a PLACSP contract type code."""

    normalized = _catalog_key(value)
    return PLACSP_CONTRACT_TYPES.get(normalized) or normalize_text(value)


def placsp_procedure_type_label(value: str | None) -> str | None:
    """Return the public label for a PLACSP procedure type code."""

    normalized = _catalog_key(value)
    return PLACSP_PROCEDURE_TYPES.get(normalized) or normalize_text(value)


def source_label(source: TenderSource) -> str:
    """Return a compact public label for a source."""

    return source.value.upper()


def status_label(status: TenderStatus) -> str:
    """Return a public label for a normalized tender status."""

    return STATUS_LABELS.get(status, status.value)


def dataset_kind_label(value: str | None) -> str | None:
    """Return a public label for a PLACSP dataset family."""

    normalized = _catalog_key(value).lower()
    return PLACSP_DATASET_KINDS.get(normalized) or normalize_text(value)


def cpv_sector_label(prefix: str) -> str | None:
    """Return a public label for a two-digit CPV division."""

    return CPV_SECTORS.get(prefix[:2])


def _catalog_key(value: str | None) -> str:
    return (normalize_text(value) or "").upper()
