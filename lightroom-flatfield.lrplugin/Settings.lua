local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrFileUtils = import "LrFileUtils"
local LrFunctionContext = import "LrFunctionContext"
local LrPathUtils = import "LrPathUtils"
local LrPrefs = import "LrPrefs"
local LrView = import "LrView"

local bind = LrView.bind
local prefs = LrPrefs.prefsForPlugin()

local Settings = {}

local CONFIG_FILENAME = "ffcplugin.config"

local function trim(value)
    if value == nil then
        return ""
    end

    return tostring(value):match("^%s*(.-)%s*$")
end

local function isWindows()
    if package and package.config and package.config:sub(1, 1) == "\\" then
        return true
    end

    local pluginPath = (_PLUGIN and _PLUGIN.path) or ""
    return pluginPath:match("^%a:[/\\]") ~= nil or pluginPath:find("\\", 1, true) ~= nil
end

local function pathExists(path)
    if trim(path) == "" then
        return false
    end

    local exists = LrFileUtils.exists(path)
    return exists == true or exists == "file"
end

local function chooseFile(title, fileTypes)
    local result = LrDialogs.runOpenPanel {
        title = title,
        prompt = "Choose",
        canChooseFiles = true,
        canChooseDirectories = false,
        allowsMultipleSelection = false,
        fileTypes = fileTypes,
    }

    if result and result[1] then
        return result[1]
    end

    return nil
end

local function repoRoot()
    if _PLUGIN and _PLUGIN.path then
        return LrPathUtils.parent(_PLUGIN.path)
    end

    return "."
end

local function repoPath(first, second)
    local path = LrPathUtils.child(repoRoot(), first)
    if second then
        path = LrPathUtils.child(path, second)
    end
    return path
end

local function unquote(value)
    value = trim(value)
    local first = value:sub(1, 1)
    local last = value:sub(-1)
    if #value >= 2 and ((first == '"' and last == '"') or (first == "'" and last == "'")) then
        value = value:sub(2, -2)
    end
    return value:gsub('\\"', '"'):gsub("\\\\", "\\")
end

local function valueFor(settings, config, key, defaultValue)
    local configValue = trim(config[key])
    if configValue ~= "" then
        return configValue
    end

    local prefValue = trim(settings[key])
    if prefValue ~= "" then
        return prefValue
    end

    return defaultValue or ""
end

local function prefValueFor(settings, key, defaultValue)
    local prefValue = trim(settings[key])
    if prefValue ~= "" then
        return prefValue
    end

    return defaultValue or ""
end

local function setDisplay(properties, values)
    properties.pythonCommand = values.pythonCommand
    properties.helperScriptPath = values.helperScriptPath
    properties.applyScriptPath = values.applyScriptPath
    properties.exiftoolPath = Settings.displayValue(values.exiftoolPath, "(not configured)")
    properties.outputSubfolder = values.outputSubfolder
    properties.backend = values.backend
    properties.compressor = values.compressor
    properties.compression = values.compression
    properties.smoothSigma = values.smoothSigma
    properties.normPercentile = values.normPercentile
    properties.dustCorrection = values.dustCorrection
    properties.dustSigma = values.dustSigma
    properties.dustThreshold = values.dustThreshold
    properties.dustAmount = values.dustAmount
    properties.dustMaxGain = values.dustMaxGain
    properties.dnglabPath = Settings.displayValue(values.dnglabPath, "(auto)")
    properties.dngConverterPath = Settings.displayValue(values.dngConverterPath, "(auto)")
    properties.pipelineSummary = "backend=" .. values.backend
        .. ", compressor=" .. values.compressor
        .. ", compression=" .. values.compression
        .. ", smoothSigma=" .. values.smoothSigma
        .. ", normPercentile=" .. values.normPercentile
        .. ", dustCorrection=" .. values.dustCorrection
    if values.configError and values.configError ~= "" then
        properties.configStatus = values.configError
    else
        properties.configStatus = "Loaded config: " .. values.configPath
    end
end

function Settings.defaultConfigPath()
    if _PLUGIN and _PLUGIN.path then
        return LrPathUtils.child(_PLUGIN.path, CONFIG_FILENAME)
    end

    return CONFIG_FILENAME
end

function Settings.defaultPythonCommand()
    local venvPython
    if isWindows() then
        venvPython = LrPathUtils.child(repoPath(".venv", "Scripts"), "python.exe")
    else
        venvPython = LrPathUtils.child(repoPath(".venv", "bin"), "python")
    end

    if pathExists(venvPython) then
        return venvPython
    end

    if isWindows() then
        return "python"
    end

    return "python3"
end

function Settings.defaultHelperScriptPath()
    return repoPath("scripts", "stage_calibration.py")
end

function Settings.defaultApplyScriptPath()
    return repoPath("scripts", "run_ffc_apply.py")
end

function Settings.readConfig(path)
    path = trim(path)
    local values = {}

    if path == "" then
        return values, "No config file path is set."
    end

    local file = io.open(path, "rb")
    if not file then
        return values, "Config file not found: " .. path
    end

    for line in file:lines() do
        local cleaned = trim(line:gsub("\r", ""))
        if cleaned ~= "" and cleaned:sub(1, 1) ~= "#" then
            local key, value = cleaned:match("^([A-Za-z0-9_]+)%s*=%s*(.-)%s*$")
            if key then
                values[key] = unquote(value)
            end
        end
    end

    file:close()
    return values, nil
end

function Settings.get()
    return {
        configPath = trim(prefs.configPath),
        pythonCommand = trim(prefs.pythonCommand),
        helperScriptPath = trim(prefs.helperScriptPath),
        applyScriptPath = trim(prefs.applyScriptPath),
        exiftoolPath = trim(prefs.exiftoolPath),
        outputSubfolder = trim(prefs.outputSubfolder),
        backend = trim(prefs.backend),
        compressor = trim(prefs.compressor),
        compression = trim(prefs.compression),
        smoothSigma = trim(prefs.smoothSigma),
        normPercentile = trim(prefs.normPercentile),
        dustCorrection = trim(prefs.dustCorrection),
        dustSigma = trim(prefs.dustSigma),
        dustThreshold = trim(prefs.dustThreshold),
        dustAmount = trim(prefs.dustAmount),
        dustMaxGain = trim(prefs.dustMaxGain),
        dnglabPath = trim(prefs.dnglabPath),
        dngConverterPath = trim(prefs.dngConverterPath),
    }
end

function Settings.effective(settings)
    settings = settings or Settings.get()
    local configPath = trim(settings.configPath) ~= "" and trim(settings.configPath) or Settings.defaultConfigPath()
    local config, configError = Settings.readConfig(configPath)

    return {
        configPath = configPath,
        configError = configError,
        pythonCommand = valueFor(settings, config, "pythonCommand", Settings.defaultPythonCommand()),
        helperScriptPath = valueFor(settings, config, "helperScriptPath", Settings.defaultHelperScriptPath()),
        applyScriptPath = valueFor(settings, config, "applyScriptPath", Settings.defaultApplyScriptPath()),
        exiftoolPath = valueFor(settings, config, "exiftoolPath", ""),
        outputSubfolder = valueFor(settings, config, "outputSubfolder", "flatfield-corrected"),
        backend = valueFor(settings, config, "backend", "auto"),
        compressor = valueFor(settings, config, "compressor", "auto"),
        compression = valueFor(settings, config, "compression", "auto"),
        smoothSigma = valueFor(settings, config, "smoothSigma", "192"),
        normPercentile = valueFor(settings, config, "normPercentile", "70"),
        dustCorrection = prefValueFor(settings, "dustCorrection", "false"),
        dustSigma = valueFor(settings, config, "dustSigma", "32"),
        dustThreshold = valueFor(settings, config, "dustThreshold", "0.02"),
        dustAmount = valueFor(settings, config, "dustAmount", "1.0"),
        dustMaxGain = valueFor(settings, config, "dustMaxGain", "1.10"),
        dnglabPath = valueFor(settings, config, "dnglabPath", ""),
        dngConverterPath = valueFor(settings, config, "dngConverterPath", ""),
    }
end

function Settings.save(settings)
    prefs.configPath = trim(settings.configPath)
    prefs.pythonCommand = trim(settings.pythonCommand)
    prefs.helperScriptPath = trim(settings.helperScriptPath)
    prefs.applyScriptPath = trim(settings.applyScriptPath)
    prefs.exiftoolPath = trim(settings.exiftoolPath)
    prefs.outputSubfolder = trim(settings.outputSubfolder)
    prefs.backend = trim(settings.backend)
    prefs.compressor = trim(settings.compressor)
    prefs.compression = trim(settings.compression)
    prefs.smoothSigma = trim(settings.smoothSigma)
    prefs.normPercentile = trim(settings.normPercentile)
    if settings.dustCorrection ~= nil then
        prefs.dustCorrection = trim(settings.dustCorrection)
    end
    prefs.dustSigma = trim(settings.dustSigma)
    prefs.dustThreshold = trim(settings.dustThreshold)
    prefs.dustAmount = trim(settings.dustAmount)
    prefs.dustMaxGain = trim(settings.dustMaxGain)
    prefs.dnglabPath = trim(settings.dnglabPath)
    prefs.dngConverterPath = trim(settings.dngConverterPath)
end

function Settings.saveApplyOptions(settings)
    prefs.dustCorrection = trim(settings.dustCorrection)
end

function Settings.displayValue(value, defaultValue)
    local cleaned = trim(value)
    if cleaned == "" then
        return defaultValue or "(auto)"
    end

    return cleaned
end

function Settings.pathExists(path)
    return pathExists(path)
end

function Settings.showDialog()
    LrFunctionContext.callWithContext("FlatFieldStagerSettings", function(context)
        local current = Settings.get()
        local effective = Settings.effective(current)
        local f = LrView.osFactory()
        local properties = LrBinding.makePropertyTable(context)

        properties.configPath = effective.configPath
        setDisplay(properties, effective)

        local function reloadConfig()
            local currentSettings = Settings.get()
            currentSettings.configPath = properties.configPath
            local reloaded = Settings.effective(currentSettings)
            setDisplay(properties, reloaded)
        end

        local contents = f:column {
            bind_to_object = properties,
            spacing = f:control_spacing(),

            f:static_text {
                title = "Run scripts/init_lightroom_config.py to install dependencies, create/update the repo venv, and generate this config file.",
                fill_horizontal = 1,
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "Config file",
                    width = 120,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "configPath",
                    width_in_chars = 58,
                },
                f:push_button {
                    title = "Choose...",
                    action = function()
                        local path = chooseFile("Choose ffcplugin.config", { "config", "txt" })
                        if path then
                            properties.configPath = path
                            reloadConfig()
                        end
                    end,
                },
                f:push_button {
                    title = "Load",
                    action = reloadConfig,
                },
            },

            f:static_text {
                title = bind "configStatus",
                fill_horizontal = 1,
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text { title = "Python", width = 120, alignment = "right" },
                f:static_text { title = bind "pythonCommand", fill_horizontal = 1 },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text { title = "Staging helper", width = 120, alignment = "right" },
                f:static_text { title = bind "helperScriptPath", fill_horizontal = 1 },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text { title = "Apply helper", width = 120, alignment = "right" },
                f:static_text { title = bind "applyScriptPath", fill_horizontal = 1 },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text { title = "ExifTool", width = 120, alignment = "right" },
                f:static_text { title = bind "exiftoolPath", fill_horizontal = 1 },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text { title = "dnglab", width = 120, alignment = "right" },
                f:static_text { title = bind "dnglabPath", fill_horizontal = 1 },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text { title = "DNG Converter", width = 120, alignment = "right" },
                f:static_text { title = bind "dngConverterPath", fill_horizontal = 1 },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text { title = "Pipeline", width = 120, alignment = "right" },
                f:static_text {
                    title = bind "pipelineSummary",
                    fill_horizontal = 1,
                },
            },
        }

        local result = LrDialogs.presentModalDialog {
            title = "Flat-Field Stager Settings",
            contents = contents,
            actionVerb = "Save Config Path",
        }

        if result == "ok" then
            Settings.save {
                configPath = properties.configPath,
            }
        end
    end)
end

return Settings
