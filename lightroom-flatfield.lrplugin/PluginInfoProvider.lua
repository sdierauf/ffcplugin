local Settings = require "Settings"

local PluginInfoProvider = {}

function PluginInfoProvider.sectionsForTopOfDialog(f, propertyTable)
    local settings = Settings.effective()
    local helperStatus = "not found"
    local applyStatus = "not found"

    if Settings.pathExists(settings.helperScriptPath) then
        helperStatus = "found"
    end

    if Settings.pathExists(settings.applyScriptPath) then
        applyStatus = "found"
    end

    return {
        {
            title = "Flat-Field Stager",
            bind_to_object = propertyTable,

            f:column {
                spacing = f:control_spacing(),
                fill_horizontal = 1,

                f:static_text {
                    title = "Command: Library > Plug-in Extras > Stage Flat-Field Calibration Frame...",
                    fill_horizontal = 1,
                },
                f:static_text {
                    title = "Config: " .. settings.configPath .. (settings.configError and " (" .. settings.configError .. ")" or ""),
                    fill_horizontal = 1,
                },
                f:static_text {
                    title = "Python: " .. Settings.displayValue(settings.pythonCommand, Settings.defaultPythonCommand()),
                    fill_horizontal = 1,
                },
                f:static_text {
                    title = "Staging helper: " .. settings.helperScriptPath .. " (" .. helperStatus .. ")",
                    fill_horizontal = 1,
                },
                f:static_text {
                    title = "Python apply helper: " .. settings.applyScriptPath .. " (" .. applyStatus .. ")",
                    fill_horizontal = 1,
                },
                f:static_text {
                    title = "Python pipeline: backend=" .. settings.backend .. ", compressor=" .. settings.compressor .. ", norm percentile=" .. settings.normPercentile .. ", dust correction=" .. settings.dustCorrection .. ", output subfolder=" .. settings.outputSubfolder,
                    fill_horizontal = 1,
                },
                f:static_text {
                    title = "ExifTool: " .. Settings.displayValue(settings.exiftoolPath, "not configured"),
                    fill_horizontal = 1,
                },
                f:static_text {
                    title = "dnglab: " .. Settings.displayValue(settings.dnglabPath, "auto-detect on PATH"),
                    fill_horizontal = 1,
                },
                f:push_button {
                    title = "Configure...",
                    action = function()
                        Settings.showDialog()
                    end,
                },
            },
        },
    }
end

return PluginInfoProvider
