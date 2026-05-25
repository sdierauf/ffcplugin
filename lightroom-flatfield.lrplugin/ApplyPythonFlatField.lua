local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrFileUtils = import "LrFileUtils"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local Settings = require "Settings"

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

local function shellQuote(arg)
    arg = tostring(arg or "")

    if isWindows() then
        return '"' .. arg:gsub('"', '\\"') .. '"'
    end

    return "'" .. arg:gsub("'", "'\\''") .. "'"
end

local function commandPrefix(command)
    command = trim(command)

    if command == "" then
        command = Settings.defaultPythonCommand()
    end

    if command:find("/", 1, true) or command:find("\\", 1, true) or command:match("^%a:") then
        return shellQuote(command)
    end

    return command
end

local function writeTextFile(path, text)
    local file, err = io.open(path, "wb")
    if not file then
        return nil, err
    end

    file:write(text)
    file:close()
    return true
end

local function readTextFile(path)
    local file = io.open(path, "rb")
    if not file then
        return nil
    end

    local text = file:read("*a")
    file:close()
    return text
end

local function readLines(path)
    local lines = {}
    local text = readTextFile(path) or ""

    for line in text:gmatch("[^\r\n]+") do
        if trim(line) ~= "" then
            table.insert(lines, line)
        end
    end

    return lines
end

local function urlDecode(value)
    value = tostring(value or "")
    value = value:gsub("+", " ")
    return (value:gsub("%%(%x%x)", function(hex)
        return string.char(tonumber(hex, 16))
    end))
end

local function parseResult(text)
    local result = {}

    for line in tostring(text or ""):gmatch("[^\r\n]+") do
        local key, value = line:match("^([^=]+)=(.*)$")
        if key then
            result[key] = urlDecode(value)
        end
    end

    return result
end

local function tempPath(suffix)
    local tempDir = LrPathUtils.getStandardFilePath("temp")
    local name = "ffcplugin-" .. tostring(os.time()) .. "-" .. tostring(math.random(100000, 999999)) .. suffix
    return LrPathUtils.child(tempDir, name)
end

local function chooseCalibrationPath()
    local result = LrDialogs.runOpenPanel {
        title = "Choose flat-field calibration raw",
        prompt = "Choose",
        canChooseFiles = true,
        canChooseDirectories = false,
        allowsMultipleSelection = false,
    }

    if result and result[1] then
        return result[1]
    end

    return nil
end

local function getSelectedPhotos(catalog)
    local activePhoto = catalog:getTargetPhoto()
    if not activePhoto then
        return {}
    end

    local photos = catalog:getTargetPhotos()

    if not photos or #photos == 0 then
        photos = { activePhoto }
    end

    return photos or {}
end

local function getPhotoPaths(photos)
    local paths = {}

    for _, photo in ipairs(photos) do
        local ok, path = LrTasks.pcall(function()
            return photo:getRawMetadata("path")
        end)

        if ok and path and path ~= "" then
            table.insert(paths, path)
        end
    end

    return paths
end

local function addOptional(parts, flag, value)
    if trim(value) ~= "" then
        table.insert(parts, flag)
        table.insert(parts, shellQuote(value))
    end
end

local function buildCommand(settings, calibrationPath, selectedListPath, outputListPath, resultPath)
    local parts = {
        commandPrefix(settings.pythonCommand),
        shellQuote(settings.applyScriptPath),
        "--calibration",
        shellQuote(calibrationPath),
        "--selected-list",
        shellQuote(selectedListPath),
        "--output-list",
        shellQuote(outputListPath),
        "--result-file",
        shellQuote(resultPath),
        "--output-subdir",
        shellQuote(settings.outputSubfolder),
        "--backend",
        shellQuote(settings.backend),
        "--compressor",
        shellQuote(settings.compressor),
        "--compression",
        shellQuote(settings.compression),
        "--smooth-sigma",
        shellQuote(settings.smoothSigma),
    }

    addOptional(parts, "--dnglab", settings.dnglabPath)
    addOptional(parts, "--dng-converter", settings.dngConverterPath)

    return table.concat(parts, " ")
end

local function importOutputs(catalog, outputPaths)
    local imported = {}
    local err = nil

    local ok = LrTasks.pcall(function()
        catalog:withWriteAccessDo("Import Python flat-field DNGs", function()
            for _, path in ipairs(outputPaths) do
                local photo = catalog:findPhotoByPath(path)
                if not photo then
                    photo = catalog:addPhoto(path)
                end
                if photo then
                    table.insert(imported, photo)
                end
            end
        end)
    end)

    if not ok then
        err = "Lightroom could not import one or more generated DNGs."
    end

    return imported, err
end

local function selectPhotos(catalog, photos)
    if #photos == 0 then
        return
    end

    local active = photos[1]
    local others = {}
    for index = 2, #photos do
        table.insert(others, photos[index])
    end

    catalog:setSelectedPhotos(active, others)
end

local function cleanup(paths)
    for _, path in ipairs(paths) do
        if path then
            LrTasks.pcall(function()
                LrFileUtils.delete(path)
            end)
        end
    end
end

local function fail(message)
    error(message, 0)
end

local function run()
    local tempFiles = {}

    local ok, err = LrTasks.pcall(function()
        local catalog = LrApplication.activeCatalog()
        local photos = getSelectedPhotos(catalog)

        if #photos == 0 then
            fail("Select one or more raw scan photos before running the Python flat-field pipeline.")
        end

        local photoPaths = getPhotoPaths(photos)
        if #photoPaths == 0 then
            fail("Lightroom did not provide filesystem paths for the selected photos.")
        end

        local calibrationPath = chooseCalibrationPath()
        if not calibrationPath then
            return
        end

        local settings = Settings.effective()
        if not Settings.pathExists(settings.applyScriptPath) then
            fail("The Python apply helper was not found:\n\n" .. settings.applyScriptPath .. "\n\nUse Configure Flat-Field Stager to choose scripts/run_ffc_apply.py.")
        end

        local selectedListPath = tempPath("-selected.txt")
        local outputListPath = tempPath("-outputs.txt")
        local resultPath = tempPath("-result.txt")
        table.insert(tempFiles, selectedListPath)
        table.insert(tempFiles, outputListPath)
        table.insert(tempFiles, resultPath)

        local wrote, writeErr = writeTextFile(selectedListPath, table.concat(photoPaths, "\n") .. "\n")
        if not wrote then
            fail("Could not write selected-photo list: " .. tostring(writeErr))
        end

        local exitCode = LrTasks.execute(buildCommand(settings, calibrationPath, selectedListPath, outputListPath, resultPath))
        local result = parseResult(readTextFile(resultPath))

        if exitCode ~= 0 or result.status ~= "ok" then
            fail(result.message ~= "" and result.message or "The Python flat-field helper failed.")
        end

        local outputPaths = readLines(outputListPath)
        if #outputPaths == 0 then
            fail("The Python flat-field helper did not report any output DNGs.")
        end

        local imported, importErr = importOutputs(catalog, outputPaths)
        if #imported == 0 then
            fail("The DNGs were generated, but Lightroom could not import them:\n\n" .. tostring(importErr))
        end

        selectPhotos(catalog, imported)

        local warning = trim(result.warning)
        local message = "Generated and imported " .. tostring(#imported) .. " flat-field corrected DNGs in:\n" .. tostring(result.output_dir)
        local style = "info"
        if warning ~= "" then
            message = message .. "\n\nWarning: " .. warning
            style = "warning"
        end

        LrDialogs.message("Python flat-field correction complete", message, style)
    end)

    cleanup(tempFiles)

    if not ok then
        LrDialogs.message("Python Flat-Field Pipeline", tostring(err), "critical")
    end
end

LrTasks.startAsyncTask(run, "Apply Flat-Field With Python Pipeline")
