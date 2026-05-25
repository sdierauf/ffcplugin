local Settings = require "Settings"

local PluginInfoProvider = {}

function PluginInfoProvider.sectionsForTopOfDialog(f, propertyTable)
    local settings = Settings.effective()
    local helperStatus = "not found"

    if Settings.pathExists(settings.helperScriptPath) then
        helperStatus = "found"
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
                    title = "Python: " .. Settings.displayValue(settings.pythonCommand, Settings.defaultPythonCommand()),
                    fill_horizontal = 1,
                },
                f:static_text {
                    title = "Helper: " .. settings.helperScriptPath .. " (" .. helperStatus .. ")",
                    fill_horizontal = 1,
                },
                f:static_text {
                    title = "ExifTool: " .. Settings.displayValue(settings.exiftoolPath, "auto-detect on PATH"),
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
