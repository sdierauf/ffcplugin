local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrTasks = import "LrTasks"
local LrView = import "LrView"

local ApplyPythonFlatField = require "ApplyPythonFlatField"
local Settings = require "Settings"
local StageFlatField = require "StageFlatField"

local function button(f, title, result)
    return f:push_button {
        title = title,
        width = 260,
        action = function(control)
            LrDialogs.stopModalWithResult(control, result)
        end,
    }
end

local function chooseAction()
    local choice = nil

    LrFunctionContext.callWithContext("FlatFieldCorrectionMenu", function()
        local f = LrView.osFactory()

        local contents = f:column {
            spacing = f:control_spacing(),

            button(f, "Stage Calibration Frame...", "stage"),
            button(f, "Apply Python Pipeline...", "apply"),
            button(f, "Configure...", "configure"),
        }

        choice = LrDialogs.presentModalDialog {
            title = "Flat Field Correction",
            contents = contents,
            actionVerb = "Close",
            cancelVerb = "< exclude >",
        }
    end)

    return choice
end

local function run()
    local choice = chooseAction()

    if choice == "stage" then
        StageFlatField.run()
    elseif choice == "apply" then
        ApplyPythonFlatField.run()
    elseif choice == "configure" then
        Settings.showDialog()
    end
end

LrTasks.startAsyncTask(run, "Flat Field Correction")
