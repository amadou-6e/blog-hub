"""Provision a disposable Skyvern organization; never print its credential."""
import asyncio
import json
from pathlib import Path
from skyvern.forge import app
from skyvern.forge.sdk.services.org_auth_token_service import create_org_api_token

async def main():
    target = Path('/app/.skyvern/credentials.toml')
    if target.exists():
        return
    organization = await app.DATABASE.organizations.create_organization('BlogHub validation')
    credential = await create_org_api_token(organization.organization_id)
    target.parent.mkdir(exist_ok=True, parents=True)
    target.write_text('[skyvern]\n[[skyvern.configs]]\nenv = "local"\nhost = "http://skyvern:8000"\n[[skyvern.configs.orgs]]\nname = "BlogHub validation"\ncred = ' + json.dumps(credential.token) + '\n')
    target.chmod(0o600)
    print('Disposable Skyvern organization ready')

asyncio.run(main())
