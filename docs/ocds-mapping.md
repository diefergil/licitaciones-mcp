# OCDS Mapping

`licitaciones-mcp` exports a pragmatic Open Contracting Data Standard (OCDS) 1.1 release package for normalized tender records.

## Release Package

The package uses OCDS `version` `1.1`. This is the OCDS schema version, not the application release version.

Default package metadata:

- `publisher.name`: `licitaciones-mcp`
- `publisher.uri`: `https://github.com/diefergil/licitaciones-mcp`
- `license`: `https://creativecommons.org/publicdomain/zero/1.0/`
- `publicationPolicy`: this document

Deployments can override publisher, license, publication policy, package URI, and OCDS version through `build_release_package` parameters.

## Tender Mapping

- `ocid`: deterministic ID from source and external ID.
- `id`: `<source>-<external_id>`.
- `date`: source publication date when available, otherwise export time.
- `tag`: `tender`.
- `language`: `es`.
- `parties`: buyer party when buyer name or tax ID is present.
- `buyer`: mirrors the buyer party.
- `tender.id`: source external ID.
- `tender.title`: normalized tender title.
- `tender.status`: mapped from internal tender lifecycle.
- `tender.description`: source summary when available.
- `tender.procurementMethodDetails`: procedure type when available.
- `tender.mainProcurementCategory`: contract type when available.
- `tender.value`: estimated value and currency.
- `tender.items`: CPV classifications.
- `tender.tenderPeriod.endDate`: tender deadline.
- `tender.documents`: source documents plus notice URL when available.
- `awards`: emitted for awarded tenders with a known winner.

## Current Limitations

The mapper is intentionally conservative. It does not yet model lots, amendment history, full eForms fields, detailed organization addresses, award criteria, contract implementation, or record-level compiled releases.
