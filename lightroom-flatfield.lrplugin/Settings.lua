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

function Settings.defaultApplyScriptPath()
    if _PLUGIN and _PLUGIN.path then
        local repoRoot = LrPathUtils.parent(_PLUGIN.path)
        return LrPathUtils.child(LrPathUtils.child(repoRoot, "scripts"), "run_ffc_apply.py")
    end

    return LrPathUtils.child("scripts", "run_ffc_apply.py")
end

function Settings.get()
    return {
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
        dnglabPath = trim(prefs.dnglabPath),
        dngConverterPath = trim(prefs.dngConverterPath),
    }
end

function Settings.effective(settings)
    settings = settings or Settings.get()

    return {
        pythonCommand = trim(settings.pythonCommand) ~= "" and trim(settings.pythonCommand) or Settings.defaultPythonCommand(),
        helperScriptPath = trim(settings.helperScriptPath) ~= "" and trim(settings.helperScriptPath) or Settings.defaultHelperScriptPath(),
        applyScriptPath = trim(settings.applyScriptPath) ~= "" and trim(settings.applyScriptPath) or Settings.defaultApplyScriptPath(),
        exiftoolPath = trim(settings.exiftoolPath),
        outputSubfolder = trim(settings.outputSubfolder) ~= "" and trim(settings.outputSubfolder) or "flatfield-corrected",
        backend = trim(settings.backend) ~= "" and trim(settings.backend) or "auto",
        compressor = trim(settings.compressor) ~= "" and trim(settings.compressor) or "auto",
        compression = trim(settings.compression) ~= "" and trim(settings.compression) or "auto",
        smoothSigma = trim(settings.smoothSigma) ~= "" and trim(settings.smoothSigma) or "192",
        normPercentile = trim(settings.normPercentile) ~= "" and trim(settings.normPercentile) or "70",
        dnglabPath = trim(settings.dnglabPath),
        dngConverterPath = trim(settings.dngConverterPath),
    }
end

function Settings.save(settings)
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
    prefs.dnglabPath = trim(settings.dnglabPath)
    prefs.dngConverterPath = trim(settings.dngConverterPath)
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
        properties.applyScriptPath = current.applyScriptPath
        properties.exiftoolPath = current.exiftoolPath
        properties.outputSubfolder = current.outputSubfolder
        properties.backend = current.backend
        properties.compressor = current.compressor
        properties.compression = current.compression
        properties.smoothSigma = current.smoothSigma
        properties.normPercentile = current.normPercentile
        properties.dnglabPath = current.dnglabPath
        properties.dngConverterPath = current.dngConverterPath

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
                    title = "Staging helper",
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
                    title = "Python apply helper",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "applyScriptPath",
                    width_in_chars = 48,
                },
                f:push_button {
                    title = "Choose...",
                    action = function()
                        local path = chooseFile("Choose run_ffc_apply.py", { "py" })
                        if path then
                            properties.applyScriptPath = path
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

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "Output subfolder",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "outputSubfolder",
                    width_in_chars = 48,
                },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "Backend",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "backend",
                    width_in_chars = 16,
                },
                f:static_text {
                    title = "auto, numpy, numexpr, or mlx",
                },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "Compressor",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "compressor",
                    width_in_chars = 16,
                },
                f:static_text {
                    title = "auto, dnglab, adobe, or none",
                },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "Compression",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "compression",
                    width_in_chars = 16,
                },
                f:static_text {
                    title = "auto, lossless-jpeg, lossless-jxl, or none",
                },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "Smooth sigma",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "smoothSigma",
                    width_in_chars = 16,
                },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "Norm percentile",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "normPercentile",
                    width_in_chars = 16,
                },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "dnglab path",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "dnglabPath",
                    width_in_chars = 48,
                },
                f:push_button {
                    title = "Choose...",
                    action = function()
                        local path = chooseFile("Choose dnglab executable")
                        if path then
                            properties.dnglabPath = path
                        end
                    end,
                },
            },

            f:row {
                spacing = f:control_spacing(),
                f:static_text {
                    title = "DNG Converter path",
                    width = 150,
                    alignment = "right",
                },
                f:edit_field {
                    value = bind "dngConverterPath",
                    width_in_chars = 48,
                },
                f:push_button {
                    title = "Choose...",
                    action = function()
                        local path = chooseFile("Choose Adobe DNG Converter")
                        if path then
                            properties.dngConverterPath = path
                        end
                    end,
                },
            },

            f:static_text {
                title = "For the Python pipeline, set Python to this repo's .venv/bin/python or another environment with the package dependencies installed.",
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
                applyScriptPath = properties.applyScriptPath,
                exiftoolPath = properties.exiftoolPath,
                outputSubfolder = properties.outputSubfolder,
                backend = properties.backend,
                compressor = properties.compressor,
                compression = properties.compression,
                smoothSigma = properties.smoothSigma,
                normPercentile = properties.normPercentile,
                dnglabPath = properties.dnglabPath,
                dngConverterPath = properties.dngConverterPath,
            }
        end
    end)
end

return Settings
