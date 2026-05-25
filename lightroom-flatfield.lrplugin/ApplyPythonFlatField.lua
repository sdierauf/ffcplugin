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

local function getPhotoPath(photo)
    local ok, path = LrTasks.pcall(function()
        return photo:getRawMetadata("path")
    end)

    if ok and path and path ~= "" then
        return path
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
        local path = getPhotoPath(photo)
        if path then
            table.insert(paths, path)
        end
    end

    return paths
end

local function chooseCalibration(catalog, photos)
    local activePhoto = catalog:getTargetPhoto()
    local activePath = activePhoto and getPhotoPath(activePhoto)

    if activePath then
        local choice = LrDialogs.confirm(
            "Choose calibration source",
            "Use the active selected photo as the flat-field calibration frame, or choose a raw file from disk.",
            "Use Active Photo",
            "Choose File",
            "Cancel"
        )

        if choice == "ok" then
            local scanPhotos = {}
            for _, photo in ipairs(photos) do
                if photo ~= activePhoto then
                    table.insert(scanPhotos, photo)
                end
            end
            if #scanPhotos == 0 then
                error("When using the active selected photo as the calibration frame, select at least one scan photo too.", 0)
            end
            return activePath, scanPhotos, activePhoto
        elseif choice == "other" then
            return nil, nil, nil
        end
    end

    local calibrationPath = chooseCalibrationPath()
    if not calibrationPath then
        return nil, nil, nil
    end

    return calibrationPath, photos, nil
end

local function cropValue(settings, key, defaultValue)
    local value = settings and settings[key]
    if value == nil then
        return defaultValue
    end
    return value
end

local function getDevelopCrop(photo)
    local ok, settings = LrTasks.pcall(function()
        return photo:getDevelopSettings()
    end)

    if not ok or not settings then
        return nil
    end

    return {
        left = cropValue(settings, "CropLeft", 0),
        top = cropValue(settings, "CropTop", 0),
        right = cropValue(settings, "CropRight", 1),
        bottom = cropValue(settings, "CropBottom", 1),
        angle = cropValue(settings, "CropAngle", 0),
        orientation = cropValue(settings, "orientation", "AB"),
    }
end

local function cropLine(path, crop)
    return table.concat({
        path,
        tostring(crop.left),
        tostring(crop.top),
        tostring(crop.right),
        tostring(crop.bottom),
        tostring(crop.angle),
        tostring(crop.orientation),
    }, "\t")
end

local function writeCropList(path, photos, calibrationPhoto)
    local lines = {}
    local seen = {}

    for _, photo in ipairs(photos) do
        local photoPath = getPhotoPath(photo)
        local crop = getDevelopCrop(photo)
        if photoPath and crop then
            table.insert(lines, cropLine(photoPath, crop))
            seen[photoPath] = true
        end
    end

    if calibrationPhoto then
        local calibrationPath = getPhotoPath(calibrationPhoto)
        if calibrationPath and not seen[calibrationPath] then
            local crop = getDevelopCrop(calibrationPhoto)
            if crop then
                table.insert(lines, cropLine(calibrationPath, crop))
            end
        end
    end

    return writeTextFile(path, table.concat(lines, "\n") .. "\n")
end

local function splitTabs(line)
    local parts = {}
    for part in (tostring(line or "") .. "\t"):gmatch("(.-)\t") do
        table.insert(parts, part)
    end
    return parts
end

local function readCropFile(path)
    local crops = {}
    local text = readTextFile(path) or ""

    for line in text:gmatch("[^\r\n]+") do
        local parts = splitTabs(line)
        if #parts >= 6 then
            crops[parts[1]] = {
                left = tonumber(parts[2]) or 0,
                top = tonumber(parts[3]) or 0,
                right = tonumber(parts[4]) or 1,
                bottom = tonumber(parts[5]) or 1,
                angle = tonumber(parts[6]) or 0,
            }
        end
    end

    return crops
end

local function addOptional(parts, flag, value)
    if trim(value) ~= "" then
        table.insert(parts, flag)
        table.insert(parts, shellQuote(value))
    end
end

local function buildCommand(settings, calibrationPath, selectedListPath, cropListPath, outputListPath, outputCropListPath, resultPath)
    local parts = {
        commandPrefix(settings.pythonCommand),
        shellQuote(settings.applyScriptPath),
        "--calibration",
        shellQuote(calibrationPath),
        "--selected-list",
        shellQuote(selectedListPath),
        "--crop-list",
        shellQuote(cropListPath),
        "--output-list",
        shellQuote(outputListPath),
        "--output-crop-list",
        shellQuote(outputCropListPath),
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
        "--norm-percentile",
        shellQuote(settings.normPercentile),
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

local function applyOutputCrops(catalog, outputPaths, importedPhotos, cropListPath)
    local crops = readCropFile(cropListPath)
    local hasCrops = false
    for _ in pairs(crops) do
        hasCrops = true
        break
    end

    if not hasCrops then
        return nil
    end

    local ok = LrTasks.pcall(function()
        catalog:withWriteAccessDo("Apply Python flat-field crop settings", function()
            for index, photo in ipairs(importedPhotos) do
                local crop = crops[outputPaths[index]]
                if crop then
                    photo:applyDevelopSettings({
                        CropLeft = crop.left,
                        CropTop = crop.top,
                        CropRight = crop.right,
                        CropBottom = crop.bottom,
                        CropAngle = crop.angle,
                    })
                end
            end
        end)
    end)

    if not ok then
        return "The DNGs were imported, but Lightroom could not apply the matching crop settings."
    end

    return nil
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

        local calibrationPath, scanPhotos, calibrationPhoto = chooseCalibration(catalog, photos)
        if not calibrationPath then
            return
        end

        local photoPaths = getPhotoPaths(scanPhotos)
        if #photoPaths == 0 then
            fail("Lightroom did not provide filesystem paths for the selected photos.")
        end

        local settings = Settings.effective()
        if not Settings.pathExists(settings.applyScriptPath) then
            fail("The Python apply helper was not found:\n\n" .. settings.applyScriptPath .. "\n\nUse Configure Flat-Field Stager to choose scripts/run_ffc_apply.py.")
        end

        local selectedListPath = tempPath("-selected.txt")
        local cropListPath = tempPath("-crops.txt")
        local outputListPath = tempPath("-outputs.txt")
        local outputCropListPath = tempPath("-output-crops.txt")
        local resultPath = tempPath("-result.txt")
        table.insert(tempFiles, selectedListPath)
        table.insert(tempFiles, cropListPath)
        table.insert(tempFiles, outputListPath)
        table.insert(tempFiles, outputCropListPath)
        table.insert(tempFiles, resultPath)

        local wrote, writeErr = writeTextFile(selectedListPath, table.concat(photoPaths, "\n") .. "\n")
        if not wrote then
            fail("Could not write selected-photo list: " .. tostring(writeErr))
        end

        local wroteCrops, cropErr = writeCropList(cropListPath, scanPhotos, calibrationPhoto)
        if not wroteCrops then
            fail("Could not write crop list: " .. tostring(cropErr))
        end

        local exitCode = LrTasks.execute(buildCommand(settings, calibrationPath, selectedListPath, cropListPath, outputListPath, outputCropListPath, resultPath))
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

        local cropWarning = applyOutputCrops(catalog, outputPaths, imported, outputCropListPath)
        selectPhotos(catalog, imported)

        local warning = trim(result.warning)
        if cropWarning then
            warning = trim(warning .. "\n" .. cropWarning)
        end
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
