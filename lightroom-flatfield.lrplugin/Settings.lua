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

function Settings.defaultPythonCommand()
    if isWindows() then
        return "python"
    end

    return "python3"
end

function Settings.defaultHelperScriptPath()
    if _PLUGIN and _PLUGIN.path then
        local repoRoot = LrPathUtils.parent(_PLUGIN.path)
        return LrPathUtils.child(LrPathUtils.child(repoRoot, "scripts"), "stage_calibration.py")
    end

    return LrPathUtils.child("scripts", "stage_calibration.py")
end

function Settings.get()
    return {
        pythonCommand = trim(prefs.pythonCommand),
        helperScriptPath = trim(prefs.helperScriptPath),
        exiftoolPath = trim(prefs.exiftoolPath),
    }
end

function Settings.effective(settings)
    settings = settings or Settings.get()

    return {
        pythonCommand = trim(settings.pythonCommand) ~= "" and trim(settings.pythonCommand) or Settings.defaultPythonCommand(),
        helperScriptPath = trim(settings.helperScriptPath) ~= "" and trim(settings.helperScriptPath) or Settings.defaultHelperScriptPath(),
        exiftoolPath = trim(settings.exiftoolPath),
    }
end

function Settings.save(settings)
    prefs.pythonCommand = trim(settings.pythonCommand)
    prefs.helperScriptPath = trim(settings.helperScriptPath)
    prefs.exiftoolPath = trim(settings.exiftoolPath)
end

function Settings.displayValue(value, defaultValue)
    local cleaned = trim(value)
    if cleaned == "" then
        return defaultValue or "(auto)"
    end

    return cleaned
end

function Settings.pathExists(path)
    if trim(path) == "" then
        return false
    end

    local exists = LrFileUtils.exists(path)
    return exists == true or exists == "file"
end

function Settings.showDialog()
    LrFunctionContext.callWithContext("FlatFieldStagerSettings", function(context)
        local current = Settings.get()
        local f = LrView.osFactory()
        local properties = LrBinding.makePropertyTable(context)

        properties.pythonCommand = current.pythonCommand
        properties.helperScriptPath = current.helperScriptPath
        properties.exiftoolPath = current.exiftoolPath

        local contents = f:column {
            bind_to_object = properties,
            spacing = f:control_spacing(),

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "Python command/path",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "pythonCommand",
                    width_in_chars = 48,
                },
                f:push_button {
                    title = "Choose...",
                    action = function()
                        local path = chooseFile("Choose Python executable")
                        if path then
                            properties.pythonCommand = path
                        end
                    end,
                },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "Helper script",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "helperScriptPath",
                    width_in_chars = 48,
                },
                f:push_button {
                    title = "Choose...",
                    action = function()
                        local path = chooseFile("Choose stage_calibration.py", { "py" })
                        if path then
                            properties.helperScriptPath = path
                        end
                    end,
                },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "ExifTool path",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "exiftoolPath",
                    width_in_chars = 48,
                },
                f:push_button {
                    title = "Choose...",
                    action = function()
                        local path = chooseFile("Choose exiftool executable")
                        if path then
                            properties.exiftoolPath = path
                        end
                    end,
                },
            },

            f:static_text {
                title = "Leave ExifTool blank to auto-detect it on PATH. Leave Python blank to use the platform default.",
                fill_horizontal = 1,
            },
        }

        local result = LrDialogs.presentModalDialog {
            title = "Flat-Field Stager Settings",
            contents = contents,
            actionVerb = "Save",
        }

        if result == "ok" then
            Settings.save {
                pythonCommand = properties.pythonCommand,
                helperScriptPath = properties.helperScriptPath,
                exiftoolPath = properties.exiftoolPath,
            }
        end
    end)
end

return Settings
