# Deploy to Azure Container Apps

This is the recommended production deployment path when the MCP server needs to be reached by hosted MCP clients — Microsoft Copilot Studio, web agents, internal portals. You deploy a Container App into your own Azure subscription. It runs the MCP server in HTTP transport mode pinned to a single AppWorks tenant, and is reachable at a public HTTPS FQDN that your Copilot Studio custom connector points at.

For stdio use (Claude Desktop / Code / Cursor / Cline on a workstation), you do **not** need any of this — just `pip install opentext-pa-mcp` per the root [README](../../README.md).

## Deploy

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Famitagl27%2Fopentext-pa-mcp%2Fmain%2Fdeploy%2Fazure%2Fazuredeploy.json)

The button opens the Azure portal's custom-deployment wizard pre-filled with this repo's ARM template. You'll fill in the `paServiceUrl` parameter and pick a resource group; the rest have sensible defaults.

Alternatively, deploy from the CLI:

```powershell
# Copy and edit the parameters file first.
cp deploy/azure/azuredeploy.parameters.json my-params.json
# (edit paServiceUrl and any others)

az group create --name my-mcp-rg --location eastus
az deployment group create `
  --resource-group my-mcp-rg `
  --template-file deploy/azure/azuredeploy.json `
  --parameters @my-params.json
```

## Prerequisites

- An Azure subscription where you can create a Container Apps Environment and a Log Analytics workspace.
- The AppWorks entity-service URL must be **reachable from the Container App's egress IP**. If AppWorks is on-prem, that means either:
  - A VNet-integrated Container Apps Environment with Private Link / Site-to-Site VPN / ExpressRoute back to your network, or
  - AppWorks exposed at a routable address with TLS in front. (Generally undesirable but supported.)
- An AppWorks identity that holds the **`Entity REST API Developer`** role (namespace `OpenText Entity Runtime`). Without it, the server fails at startup with HTTP 403 when fetching the OpenAPI spec. See the root README for the full role explanation.

## Parameters

| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `appName` | yes | `process-automation-mcp` | Becomes part of the Container App's FQDN. |
| `paServiceUrl` | yes | — | Full AppWorks entity-service URL (the same one you'd set as `PA_SERVICE_URL` for stdio mode). |
| `paAuthMode` | no | `auto` | `auto` / `otds` / `cordys`. Override only if auto-detection misfires. |
| `paLogLevel` | no | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `imageTag` | no | `latest` | The `ghcr.io/amitagl27/opentext-pa-mcp` tag to deploy. Pin to a specific version (e.g. `0.2.0`) in production. |
| `minReplicas` | no | `1` | Set to `0` for scale-to-zero (cheaper, but first request after idle hits a 5–15 s cold start that Copilot Studio users will notice). |
| `maxReplicas` | no | `3` | |
| `cpuCores` | no | `0.5` | vCPU per replica. |
| `memorySize` | no | `1Gi` | Memory per replica. Pair with `cpuCores` per Container Apps' allowed CPU/memory ratios. |

## After deploy

1. **Note the output `mcpEndpoint`** — Azure portal → your deployment → Outputs. It looks like `https://process-automation-mcp.<region-id>.azurecontainerapps.io/mcp`.

2. **Smoke test** the listener:

   ```powershell
   curl -i https://<your-fqdn>/mcp
   ```

   Expect HTTP 405 or 406 (MCP only accepts POST with the right `Accept` header). Either confirms the listener is up. A 200 is wrong; a connection refused means the Container App didn't start — check Log Analytics.

3. **Customize the Copilot Studio connector**: open [`deploy/copilot-studio/connector.yaml`](../copilot-studio/connector.yaml) from this repo, replace the `host:` placeholder with your deployed FQDN (without the `https://` prefix and without `/mcp`), then import the file via Power Platform → **Custom Connectors** → **New custom connector** → **Import from OpenAPI file**.

4. **Test in Copilot Studio**: create a connection on the connector (it will prompt for AppWorks username + password), add the connector as a tool to your agent, and ask the agent to list entities or query a list. AppWorks audit trails will show the queries running as the *connection-owner* user.

## Costs

Container Apps consumption plan is cheap but not zero at `minReplicas=1`:

- Roughly **\$25–60 / month** with one replica continuously warm at 0.5 vCPU / 1 Gi, plus Log Analytics ingestion (typically a few dollars at most for a low-traffic MCP).
- With `minReplicas=0`, under \$5 / month for low traffic — at the cost of cold starts.

The exact figure depends on region, traffic, and Log Analytics retention. Use the [Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/) for an accurate estimate.

## Image source

The image is built from this repo by [`.github/workflows/publish-image.yml`](../../.github/workflows/publish-image.yml) and published to `ghcr.io/amitagl27/opentext-pa-mcp`. The image is public — no GHCR authentication is needed to pull it. If you want to inspect or rebuild it yourself, the Dockerfile is at [`deploy/azure/Dockerfile`](Dockerfile).

## Updating

To roll a new version onto an existing deployment, redeploy with the same parameters but a different `imageTag` value. Container Apps performs a rolling update behind the ingress.

## Removing

```powershell
az group delete --name my-mcp-rg --yes
```

Removes the Container App, the Container Apps Environment, and the Log Analytics workspace.
