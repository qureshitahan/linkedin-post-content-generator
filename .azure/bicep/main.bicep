// Deploy Content Intelligence web apps onto an EXISTING App Service Plan.
// Does not create a new plan — keeps cost on your shared Basic/Standard tier.

@description('Azure region (must match your existing plan, e.g. eastus).')
param location string = resourceGroup().location

@description('Name of your existing App Service Plan (e.g. my-shared-plan).')
param existingAppServicePlanName string

@description('Project slug for web app names (e.g. linkedin-post-content-generator → linkedin-post-content-generator-api).')
param projectName string = 'linkedin-post-content-generator'

@description('Linux runtime stack for the API app.')
param apiRuntimeStack string = 'PYTHON|3.11'

@description('Linux runtime stack for the static frontend app.')
param webRuntimeStack string = 'NODE|20-lts'

@description('Create optional -staging web apps on the same plan (Basic tier has no deployment slots).')
param deployStagingApps bool = false

@description('Frontend production URL used in API CORS (no trailing slash).')
param frontendUrl string

var apiAppSettings = [
  {
    name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
    value: 'true'
  }
  {
    name: 'WEBSITES_PORT'
    value: '8000'
  }
  {
    name: 'PYTHONPATH'
    value: '/home/site/wwwroot'
  }
  {
    name: 'CORS_ORIGINS'
    value: frontendUrl
  }
  {
    name: 'WEBSITE_HEALTHCHECK_PATH'
    value: '/api/health'
  }
  {
    name: 'ENABLED_SOURCES'
    value: 'news,industry,hackernews,arxiv,pubmed,preprint,devto'
  }
  {
    name: 'DATABASE_URL'
    value: 'sqlite:////home/site/data/content_intelligence.db'
  }
]

var webAppSettings = [
  {
    name: 'WEBSITE_NODE_DEFAULT_VERSION'
    value: '~20'
  }
]

var apiAppName = '${projectName}-api'
var webAppName = '${projectName}-web'
var apiStagingName = '${apiAppName}-staging'
var webStagingName = '${webAppName}-staging'

resource existingPlan 'Microsoft.Web/serverfarms@2023-12-01' existing = {
  name: existingAppServicePlanName
}

resource apiApp 'Microsoft.Web/sites@2023-12-01' = {
  name: apiAppName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: existingPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: apiRuntimeStack
      alwaysOn: false // Basic tier: alwaysOn unavailable; set true if plan is Standard+
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      appCommandLine: 'bash startup.sh'
      appSettings: apiAppSettings
    }
  }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: webAppName
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: existingPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: webRuntimeStack
      alwaysOn: false
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      appCommandLine: 'bash startup.sh'
      appSettings: webAppSettings
    }
  }
}

resource apiStagingApp 'Microsoft.Web/sites@2023-12-01' = if (deployStagingApps) {
  name: apiStagingName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: existingPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: apiRuntimeStack
      alwaysOn: false
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appCommandLine: 'bash startup.sh'
      appSettings: apiAppSettings
    }
  }
}

resource webStagingApp 'Microsoft.Web/sites@2023-12-01' = if (deployStagingApps) {
  name: webStagingName
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: existingPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: webRuntimeStack
      alwaysOn: false
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appCommandLine: 'bash startup.sh'
      appSettings: webAppSettings
    }
  }
}

// Persist SQLite + generated images across restarts (Basic plan friendly).
resource apiStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take(replace('ciapi${uniqueString(resourceGroup().id, apiAppName)}', '-', ''), 24)
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource apiFileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  name: '${apiStorage.name}/default/appdata'
  properties: {
    shareQuota: 5
  }
}

resource apiMount 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: apiApp
  name: 'azurestorageaccounts'
  properties: {
    '${apiStorage.name}': {
      type: 'AzureFiles'
      accountName: apiStorage.name
      shareName: 'appdata'
      mountPath: '/home/site/data'
      accessKey: apiStorage.listKeys().keys[0].value
    }
  }
}

output apiAppName string = apiApp.name
output apiDefaultHostName string = apiApp.properties.defaultHostName
output webAppName string = webApp.name
output webDefaultHostName string = webApp.properties.defaultHostName
output apiStagingAppName string = deployStagingApps ? apiStagingApp.name : ''
output webStagingAppName string = deployStagingApps ? webStagingApp.name : ''
output apiManagedIdentityPrincipalId string = apiApp.identity.principalId
