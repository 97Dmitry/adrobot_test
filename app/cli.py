"""Operational entry point for accepting the creator before the UI is added."""

import argparse
import json
import re
import sys

from pydantic import ValidationError

from app.config import Settings
from app.creator import create_campaign
from app.database import make_engine, make_sessions
from app.errors import DomainError
from app.keitaro import KeitaroClient
from app.models import CreationOperation
from app.schemas import CreateCampaign


def _parser():
    parser = argparse.ArgumentParser(description="Keitaro wrapper: campaign creator")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalogs", help="Read available domains, campaign groups and sources")
    offers = commands.add_parser("offers", help="Search existing offers by ID or name")
    offers.add_argument("--query", default="")
    status = commands.add_parser("status", help="Read a locally saved creation operation")
    status.add_argument("--key", required=True)
    create = commands.add_parser("create", help="Create a prefixed campaign with two flows")
    create.add_argument("--name", required=True)
    create.add_argument("--countries", required=True, help="Comma-separated ISO alpha-2 codes")
    create.add_argument("--offer-id", required=True, type=int)
    create.add_argument("--domain-id", required=True, type=int)
    create.add_argument("--group-id", required=True, type=int)
    create.add_argument("--source-id", required=True, type=int)
    create.add_argument(
        "--key", required=True, help="Stable operation key; reuse it for reconciliation"
    )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings()
    engine = None
    try:
        request = None
        if args.command == "create":
            request = CreateCampaign(
                name=args.name,
                countries=[code for code in re.split(r"[,;\s]+", args.countries.strip()) if code],
                offer_id=args.offer_id,
                domain_id=args.domain_id,
                group_id=args.group_id,
                traffic_source_id=args.source_id,
            )
        with KeitaroClient(
            settings.keitaro_url,
            settings.keitaro_api_key.get_secret_value(),
            settings.keitaro_timeout,
        ) as client:
            if args.command == "catalogs":
                result = {
                    kind: [
                        {"id": item["id"], "name": item["name"]}
                        for item in items
                        if item.get("state") != "deleted"
                    ]
                    for kind, items in client.catalogs().items()
                }
            elif args.command == "offers":
                result = client.search_offers(args.query)
            else:
                engine = make_engine(settings.database_url)
                with make_sessions(engine)() as session:
                    if args.command == "create":
                        result = create_campaign(session, client, request, args.key)
                    else:
                        op = session.get(CreationOperation, args.key)
                        if op is None:
                            raise DomainError("Операция не найдена.", 404, "operation_missing")
                        result = {
                            "operation_key": op.key,
                            "campaign_id": op.campaign_id,
                            "phase": op.phase,
                            "error": op.error,
                            "result": op.result,
                        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ValidationError as error:
        print(
            json.dumps(
                {
                    "error": "Неверные параметры кампании.",
                    "details": error.errors(include_context=False, include_input=False),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    except DomainError as error:
        print(
            json.dumps(
                {"error": error.message, "code": error.code, "details": error.details},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
