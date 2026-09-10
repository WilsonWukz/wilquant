"""Foreground standalone host and hidden-input credential provisioning."""

import argparse
import getpass
from pathlib import Path

import uvicorn

from quant_lab.ai_provider_protocol import CallPolicy, EndpointProfile, ProviderFailure

from . import FakeProvider, OpenAICompatibleProvider, create_app
from .secrets import WindowsCredentialManagerSecretStore
from .token_file import HostTokenFile


def main() -> None:
    parser = argparse.ArgumentParser(description="WIL_QUANT isolated AI provider host")
    commands = parser.add_subparsers(dest="command", required=True)
    credential = commands.add_parser("set-credential")
    credential.add_argument("--credential-ref", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--profile", type=Path, required=True)
    serve.add_argument("--token-file", type=Path, required=True)
    serve.add_argument("--port", type=int, default=8011)
    serve.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "set-credential":
            secret = getpass.getpass("Secret: ")
            WindowsCredentialManagerSecretStore().set(args.credential_ref, secret)
            print("凭证已安全保存。")
            return
        profile = EndpointProfile.model_validate_json(args.profile.read_bytes())
        policy = CallPolicy()
        provider = (
            FakeProvider(profile)
            if args.fake
            else OpenAICompatibleProvider(profile, WindowsCredentialManagerSecretStore(), policy)
        )
        token_file = HostTokenFile(args.token_file)
        token = token_file.create()
        try:
            uvicorn.run(
                create_app(profile, provider, token, policy),
                host="127.0.0.1",
                port=args.port,
                access_log=False,
                log_level="warning",
            )
        finally:
            token_file.close()
    except ProviderFailure as exc:
        parser.exit(1, exc.code + "\n")
    except (OSError, ValueError):
        parser.exit(1, "HOST_CONFIGURATION_INVALID\n")


if __name__ == "__main__":
    main()
