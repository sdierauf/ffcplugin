local LrTasks = import "LrTasks"
local Settings = require "Settings"

LrTasks.startAsyncTask(function()
    Settings.showDialog()
end, "Configure Flat-Field Stager")
