ï»¿(function (otApp) {
    /*global $: false */
    /*global jQuery: false */
    /*global Globalize: false */
    /*global DOMParser: false */
    /*global otUtils: false */
    /*global window: false */
    /*global navigator: false */
    /*global builderElementCategory: false */
    /*global ot_App: false */
    /*global document: false */
    /*global document: false */
    /*global _: false */

    var solutionManagerSingleton;

    function init() {
        var elementCache = {}, uuidCache = [], mode = "production", serviceUrl, currentUserTenantElement, tenantConfigurationId = null,
            solutionCache = {}, elementTypeCache = {}, elementConfigurationCache = {}, tenantElement = null, tenantScope = "Local";
        
        var StripedSolutionConfigurationNamePrefix = "SolutionConfiguration_";

        function doAjax(uri, type, data) {
            var doingOp = otApp.ajax({
                type: type,
                url: uri,
                data: data,
                contentType: "application/json; charset=utf-8",
                dataType: "json"
            });

            return doingOp.pipe(function (reply) {
                return reply;
            }, function (reply) {
                var error = otApp.buildError(reply);
                return error;
            });
        }

        function appendConfigurationId(hasParams) {
            var seperator, configId = "";

            if (tenantConfigurationId !== null) {
                if (hasParams) {
                    seperator = "&";
                } else {
                    seperator = "?";
                }
                configId = seperator + "configurationId=" + tenantConfigurationId;
            }
            return configId;
        }        

        function appendTenantScope(hasParams) {
            var seperator, tenantScopeParam = "";

            if (tenantScope !== null) {
                if (hasParams) {
                    seperator = "&";
                } else {
                    seperator = "?";
                }
                tenantScopeParam = seperator + "tenantScope=" + tenantScope;
            }
            
            return tenantScopeParam;
        }

        function onWorkspaceDeleted(solutionWorkspace) {
            otApp.changeSetManager.removeChangeSetByContainerId(solutionWorkspace.definition.referencedSolutionId);
            removeElementFromCache(solutionWorkspace.definition.referencedSolutionId);
        }

        function getBaseUri() {
            if (!serviceUrl) {
                serviceUrl = mode === "production" ? otApp.getDefaultServiceUrl() : "../../" + otApp.getDefaultServiceUrl();
            }

            return serviceUrl;
        }

        function cacheElement(element) {
            var solutionConfigurationElements;

            // If we are about to replace a once absent parent, adopt its children.
            if (elementCache[element.id] && elementCache[element.id].temporary) {
                element.children = elementCache[element.id].children;
            }

            elementCache[element.id] = element;
            if (element.containerVersionId === null) {
                solutionConfigurationElements = elementConfigurationCache[element.containerId];
                if (solutionConfigurationElements) {
                    solutionConfigurationElements[element.id] = element;
                }
            } else {
                if (element.typeId === otApp.WellKnownElementGuids.SolutionType) {
                    solutionCache[element.id] = element;
                } else if (element.typeId === otApp.WellKnownElementGuids.ElementType) {
                    elementTypeCache[element.id] = element;
                } else if (element.typeId === otApp.WellKnownElementGuids.TenantType) {
                    tenantElement = element;
                }
            }
        }

        function cacheConfigruationElements(jObj, solutionId) {
            var solutionConfigurationElements = [];

            $.each(jObj, function (id, obj) {
                solutionConfigurationElements[id] = obj;
                elementCache[id] = obj;
            });

            elementConfigurationCache = [];
            elementConfigurationCache[solutionId] = solutionConfigurationElements;
        }

        function updateParentOf(element) {
            var parentElement, childIds, i, length, found, solutionConfigurationElements;
            // Add child to parent but only if he is not there already, and only if its not a 
            // configuration element.
            if (element && element.parentId && element.containerVersionId !== null) {
                found = false;
                parentElement = elementCache[element.parentId];
                if (parentElement !== undefined && parentElement !== null) {
                    childIds = parentElement.children;
                    if (childIds) {
                        for (i = 0, length = childIds.length; i < length; i += 1) {
                            if (childIds[i] === element.id) {
                                found = true;
                                break;
                            }
                        }

                        if (!found) {
                            parentElement.children.push(element.id);
                        }
                    } else {
                        parentElement.children = [];
                        parentElement.children.push(element.id);
                    }
                } else {
                    // Element has no parent in cache yet.  Create a temporary element so we can start
                    // accumulating its children.
                    parentElement = { id: element.parentId, children: [], temporary: true };
                    parentElement.children.push(element.id);
                    elementCache[element.parentId] = parentElement;
                }
            } else if (element.containerVersionId === null) {
                solutionConfigurationElements = elementConfigurationCache[element.containerId];
                if (solutionConfigurationElements) {
                    solutionConfigurationElements[element.id] = element;
                }
            }
        }
        
        function getUniqueIdsFromServer(howMany) {
            var count, gettingUniqueIds, uri;

            if (howMany > 100) {
                count = howMany;
            } else {
                count = 100;
            }

            uri = getBaseUri() + "GUIDS?count=" + count;

            gettingUniqueIds = ot_App.ajax({
                type: "GET",
                url: uri,
                data: "",
                contentType: "application/xml; charset=utf-8",
                dataType: "json"
            });

            return gettingUniqueIds.pipe(function (reply) {
                return reply;
            }, function (reply) {
                var error = otApp.buildError(reply);
                return error;
            });
        }

        function upgradeSolution(containerVersionId, containerId) {
            var deployingComponents, uri;

            uri = getBaseUri() + "Elements(" + containerVersionId + "." + containerId + ")/Version?action=upgrade";

            deployingComponents = ot_App.ajax({
                type: "POST",
                url: uri,
                data: "",
                contentType: "application/xml; charset=utf-8",
                dataType: "json"
            });

            return deployingComponents.pipe(function (reply) {
                return reply;
            }, function (reply) {
                var error = otApp.buildError(reply);
                return error;
            });
        }

        // Gets the tenant element.  
        function getTenant(context, tenantType) {
            var tenantUri, gettingTenant, parms = "?childDetails=true&childLevels=all&include=Definition,Usage&flat=true&includeSolutions=true";
            
            if (tenantType === undefined || tenantType === null || tenantType === "Organization") {
                tenantUri = getBaseUri() + "Elements($Tenant)" + parms;
                tenantScope = "Local";
            } else {
                tenantUri = getBaseUri() + "Elements($GlobalTenant)" + parms;
                tenantScope = "Global";
            }

            gettingTenant = ot_App.ajax({
                type: "GET",
                url: tenantUri,
                data: "",
                context: context,
                contentType: "application/json; charset=utf-8",
                dataType: "json"
            });

            return gettingTenant.pipe(function (reply) {
                return reply;
            }, function (reply) {
                var error = otApp.buildError(reply);
                return error;
            });
        }

        function recurseChildren(parentId, children, all) {
            var parentElement = elementCache[parentId], childIds, i, length, element;
            if (parentElement) {
                childIds = parentElement.children;
                if (childIds) {
                    for (i = 0, length = childIds.length; i < length; i += 1) {
                        element = elementCache[childIds[i]];
                        if (element) {
                            children.push(element);

                            if (all) {
                                recurseChildren(element.id, children, true);
                            }
                        }
                    }
                }
            }
        }

        // Gets the specified element along with all of its children.
        // versionId - this is the version id for definition elements and the solution id for configuration elements.
        // elementId - this is the element id.
        function getElementFromServer(versionId, elementId, context) {
            var uri, gettingElementFromServer, uid = _.isUndefined(versionId) ? elementId : versionId + "." + elementId;

            uri = getBaseUri() + "Elements(" + uid + ")?childDetails=true&childLevels=all&include=definition,usage&flat=true&includeSolutions=true" + appendConfigurationId(true) + appendTenantScope(true);

            gettingElementFromServer = ot_App.ajax({
                type: "GET",
                url: uri,
                data: "",
                context: context,
                contentType: "application/json; charset=utf-8",
                dataType: "json"
            });

            return gettingElementFromServer;
        }

        // Gets the specified element with none of its children.
        // versionId - this is the version id for definition elements and the solution id for configuration elements.
        // elementId - this is the element id.
        function getSingleElementFromServer(versionId, elementId) {
            var uri, gettingElementFromServer, uid = _.isUndefined(versionId) ? elementId : versionId + "." + elementId;

            uri = getBaseUri() + "Elements(" + uid + ")?childLevels=0&include=definition,usage&flat=true" + appendConfigurationId(true) + appendTenantScope(true);

            gettingElementFromServer = ot_App.ajax({
                type: "GET",
                url: uri,
                data: "",
                contentType: "application/json; charset=utf-8",
                dataType: "json"
            });

            return gettingElementFromServer;
        }

        function getSolutionConfiguration(tenantContainerVersionId, solutionWorkspaceId, configurationScope) {
            var uri, gettingSolutionConfigurations;

            uri = getBaseUri() + "Elements(" + tenantContainerVersionId + "." + solutionWorkspaceId + ")/SolutionConfigurations?flat=true&include=definition" + appendTenantScope(true);
            if (configurationScope) {
                uri = uri + "&configurationScope=" + configurationScope;
            }

            gettingSolutionConfigurations = ot_App.ajax({
                type: "GET",
                url: uri,
                data: "",
                contentType: "application/json; charset=utf-8",
                dataType: "json"
            });

            return gettingSolutionConfigurations;
        }

        function processBatchEx(databaseId, jsonObjects, containerId, useSyncCall) {
            var uri, jsonString, processingBatch, changeSet;

            uri = getBaseUri() + "Elements?changeLog=true" + appendConfigurationId(true) + appendTenantScope(true);
            if (databaseId) {
                uri += "&databaseId=" + databaseId;
            }

            if (containerId) {
                changeSet = otApp.changeSetManager.getChangeSetByContainerId(containerId);
                if (changeSet) {
                    if (changeSet.owner.containerVersionId) {
                        uri += "&containerVersionId=" + changeSet.owner.containerVersionId;
                        uri += "&versionChangeToken=" + changeSet.changeToken;
                    }
                    if (changeSet.solutionConfigurationId) {
                        uri += "&solutionConfigurationId=" + changeSet.solutionConfigurationId;
                        uri += "&configurationChangeToken=" + changeSet.configurationChangeToken;
                    }
                }
            }

            jsonString = JSON.stringify(jsonObjects);

            processingBatch = ot_App.ajax({
                type: "PUT",
                url: uri,
                data: jsonString,
                contentType: "application/json; charset=utf-8",
                async: !useSyncCall,
                dataType: "json"
            });

            return processingBatch.pipe(function (reply) {
                return reply;
            }, function (reply) {
                var error;
                error = otApp.buildError(reply);
                return error;
            });
        }

        function processBatch(databaseId, batch) {
            var uri, processingBatch;

            uri = getBaseUri() + "Elements?delayPostCreate=true" + appendConfigurationId(true) + appendTenantScope(true);
            if (databaseId) {
                uri += "&databaseId=" + databaseId;
            }

            processingBatch = ot_App.ajax({
                type: "PUT",
                url: uri,
                data: batch,
                contentType: "application/xml; charset=utf-8",
                dataType: "text"
            });

            return processingBatch.pipe(function (reply) {
                return reply;
            }, function (reply) {
                var error = otApp.buildError(reply);
                return error;
            });
        }

        function getImmediateChildrenSorted(parentId) {
            var children = [];

            recurseChildren(parentId, children, false);

            children.sort(function (item1, item2) {
                return otUtils.localeCompareForSort(item1.displayName, item2.displayName);
            });

            return children;
        }

        function orderList(parentId, children, allLevels) {
            var i, length, newChildren;

            newChildren = getImmediateChildrenSorted(parentId);

            for (i = 0, length = newChildren.length; i < length; i += 1) {
                children.push(newChildren[i]);
                if (allLevels) {
                    orderList(newChildren[i].id, children, allLevels);
                }
            }
        }

        function getChildrenInternal(parentId, allLevels, sort) {
            var children = [];

            if (!sort) {
                recurseChildren(parentId, children, allLevels);
            } else {
                orderList(parentId, children, allLevels);
            }

            return children;
        }

        function getElement(jObj, desiredId) {
            $.each(jObj, function (id, obj) {
            	if (obj.type === "Tenant") {
            		otApp.changeSetManager.addTenantChangeSet(obj, tenantScope);
            	}
            	
                cacheElement(obj);
            });

            if (desiredId) {
                return elementCache[desiredId];
            }

            return null;
        }

        function setContainerVersionId(element) {
            var parent, lastElement = element;
            if (element.containerVersionId) {
                // The element already has one, no need to set it.
                return;
            }

            while (element.containerVersionId === null) {
                parent = otApp.solutionManager.getElementById(lastElement.parentId);
                if (parent.containerVersionId) {
                    element.containerVersionId = parent.containerVersionId;
                    break;
                }

                lastElement = parent;
            }
        }

        function buildFileUploadProgressReporter(uplodingPromise) {
            return function () {
                var xhr = $.ajaxSettings.xhr();
                if (xhr.upload) {
                    xhr.upload.onprogress = function (event) {
                        var percent = 0, position, total;
                        position = event.loaded || event.position; /*event.position is deprecated*/
                        total = event.total;
                        if (event.lengthComputable) {
                            percent = Math.ceil(position / total * 100);
                        }

                        uplodingPromise.notify(event, position, total, percent);
                    };
                }

                return xhr;
            };
        }

        function buildFileUploadAjaxSettings(restUri, requestData, domFileInputForm, file, type) {
            var ajaxOptions, hasFile, hasXmlHttpLevel2, formData, $fileInput;

            // Is any file input control exist in the form.
            if (domFileInputForm !== undefined && domFileInputForm !== null) {
                $fileInput = $(":file", domFileInputForm);
            } else {
                $fileInput = null;
            }

            // Is file argument has valid value.
            hasFile = (file !== undefined && file !== null) ? true : false;

            if ($fileInput !== null || hasFile) {

                // XmlHttpRequest Level2 support (FixeFox, Chrome, Safari supports XmlHttpRequest level 2 specification.
                hasXmlHttpLevel2 = window.FormData !== undefined && (hasFile || $fileInput.get(0).files !== undefined);

                // fix bug with ie10 doesn't support FromData append correctly with file object
                if (navigator.userAgent.match(/MSIE\s([\d]+)/)) {
                    hasXmlHttpLevel2 = false;
                }

                if (hasXmlHttpLevel2) {
                    formData = new window.FormData();

                    if (requestData !== null) {
                        formData.append("request$json", JSON.stringify(requestData));
                    }

                    if (hasFile) {
                        formData.append("file1", file);
                    } else if ($fileInput) {
                        formData.append("file1", $fileInput.get(0).files[0]);
                    }

                    ajaxOptions = {
                        url: restUri,
                        data: formData,
                        processData: false,
                        type: type,
                        dataType: "json",
                        contentType: false
                    };
                } else {
                    /// Use Iframe based file upload (Internet explorer).
                    ajaxOptions = {
                        uri: restUri + "&format=json&overwriteFormat=text",
                        files: $fileInput,
                        type: type,
                        iframe: true,
                        dataType: "json"
                    };

                    if (requestData !== null) {
                        ajaxOptions.data = { "request$json": JSON.stringify(requestData) };
                        ajaxOptions.processData = false;
                    }
                }
            } else {
                ajaxOptions = null;
            }

            return ajaxOptions;
        }

        function getTypesForCategory(typeCategory) {
            var elementTypes = [], i, length;
            for (i = 0, length = elementTypeCache.length; i < length; i += 1) {
                if (elementTypeCache[i].builderElementCategory === typeCategory) {
                    elementTypes.push(elementTypeCache[i]);
                }
            }

            return elementTypes;
        }

        function inspectElements(elements, element, iterator, deep) {
            element && _.each(element.children, function (value) {
                var target = elements[value];

                if (iterator) {
                    iterator.call(target, target);
                }

                if (deep) {
                    inspectElements(elements, target, iterator, deep);
                }
            });
        }

        function findElements(elements, options) {
            if (!options) {
                options = {};
            }

            var id = options.elementId,
                criteria = options.criteria || {},
                deep = options.deep === true,
                element = elements[id],
                results = [],
                iterator = null;

            if (_.isFunction(criteria))
                (iterator = function (target) { 
                	return criteria.call(target, target); 
                	});
            else if (_.isObject(criteria)) 
            	(iterator = function (target) { 
            		return _.all(criteria, function (value, key) { 
            			return value === target[key]; 
            			}); 
            		});

            if (iterator) {
                inspectElements(elements, element, function () { 
                	if (iterator.call(this, this)) 
                		results.push(this); 
                	}, deep);
            }

            return results;
        }

        function injectViews(self, elements, containerId) {
        	var i, j, length, viewsLength, lists = self.getChildrenByTypeId(containerId,  otApp.WellKnownElementGuids.ListType);
        	for (i = 0, length = lists.length; i < length; i += 1) {
        		var views = self.getChildrenByTypeId(lists[i].id,  otApp.WellKnownElementGuids.ViewType);
        		for (j = 0, viewsLength = views.length; j < viewsLength; j += 1) {
        			elements.push(views[j]);        			
        		}
        	}        	
        }

        function showInfoBox(message) {
            var infoBox = document.createElement("div");
            infoBox.className = "info-box";
            infoBox.innerHTML = `
                    <div id="infobox">
                    <span class="info-icon">
                    <img class="status-image" src="/home/system/app/admin/web/images/notification_success24.svg" width="16" height="16">
                    </span>
                    <span class="info-message">${message}</span>
                    </div>
                    `;
            document.body.appendChild(infoBox);
            setTimeout(() => infoBox.remove(), 3000);
        }
		
		function showErrorBox(error) {
		    var errorBox = document.createElement("div");
		    errorBox.className = "error-box";
		    errorBox.innerHTML = `
			<div id="errorbox" >
			<span class="error-icon">
				<img class="status-image" src="/home/system/app/admin/web/images/notification_error24.svg" width="16" height="16">
			</span>
			<span class="error-message">${error.message}</span>
			<span class="error-close" onclick="this.closest('.error-box').remove()>
				<img class="close-image" src="/home/system/app/admin/web/images/clear-icon.svg" width="16" height="16">
			</span>
			</div>
		    `;
		    document.body.appendChild(errorBox);
		    setTimeout(() => errorbox.remove(), 5000);
		}

        function removeChild(children, childId) {
            var i, length;
            if (children && children.length > 0) {
                for (i = 0, length = children.length; i < length; i += 1) {
                    if (children[i] === childId) {
                        children.splice(i, 1);
                        break;
                    }
                }
            }
        }

        function removeElementFromCache(elementId) {
            var element, parentelement, children, i, length, solutionConfigurationElements, id, elId;

            // Remove child from parent list if necessary.
            element = elementCache[elementId];
            if (element && element.parentId) {
                parentelement = elementCache[element.parentId];
                if (parentelement) {
                    removeChild(parentelement.children, elementId);
                }
            }

            if (element) {
                // Remove all his children.
                children = getChildrenInternal(elementId, true, false);
                for (i = 0, length = children.length; i < length; i += 1) {
                    delete elementCache[children[i].id];
                }

                if (element.typeId === otApp.WellKnownElementGuids.SolutionType) {
                    delete solutionCache[elementId];
                } else if (element.typeId === otApp.WellKnownElementGuids.SolutionWorkspaceType) {
                    onWorkspaceDeleted(element);
                } else if (element.typeId === otApp.WellKnownElementGuids.ElementType) {
                    delete elementTypeCache[elementId];
                }

                if (element.containerVersionId === null) {
                    // We have configuration element, remove it from the configuration cache.
                    for (id in elementConfigurationCache) {
                        if (elementConfigurationCache.hasOwnProperty(id)) {
                            solutionConfigurationElements = elementConfigurationCache[id];
                            for (elId in solutionConfigurationElements) {
                                if (solutionConfigurationElements.hasOwnProperty(elId)) {
                                    if (solutionConfigurationElements[elId].id === elementId) {
                                        delete solutionConfigurationElements[elId];
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            delete elementCache[elementId];
        }

        // Remove all solutions from cache.
        function removeSolutions() {
            otApp.changeSetManager.clearAll();
            
            $.each(solutionCache, function (solutionCacheEntryId) {
                removeElementFromCache(solutionCacheEntryId);
            });
        }

        function synchronizeElementsInCache(changeEventInfos) {
            _.each(changeEventInfos, function (changeEventInfo) {
                var current, element;
                if (changeEventInfo.changeType === 'Create') {
                    element = changeEventInfo.element;
                    cacheElement(element);
                    updateParentOf(element);
                } else if (changeEventInfo.changeType === 'Update') {
                    current = changeEventInfo.element;
                    if (elementCache[current.id] !== undefined) {
                        current.children = elementCache[current.id].children;
                    }
                    cacheElement(current);
                } else if (changeEventInfo.changeType === 'Delete') {
                    removeElementFromCache(changeEventInfo.id);
                }
            });
        }

        function triggerChangeLogEvents(changeEventInfos, silent) {
        	_.each(changeEventInfos, function (changeEventInfo) {
        		var element;
        		if (changeEventInfo.changeType === 'Create') {
        			element = changeEventInfo.element;
        			if (element) {
        			    $(window).trigger({ type: "element:{0}:created".format(element.parentId), element: element, silent: silent });
        			}
        		} else if (changeEventInfo.changeType === 'Update') {
        			element = changeEventInfo.element;
        			if (element) {
        				$(window).trigger({ type: "element:{0}:updated".format(element.id), element: element, silent: silent });
        			}
        		} else if (changeEventInfo.changeType === 'Delete') {
        		    $(window).trigger({ type: "element:{0}:deleted".format(changeEventInfo.id), silent: silent });
        		}
        	});
        }

        return {
            getCurrentUserTenantElement: function() {
                return currentUserTenantElement;
            },
            
            getConfigurationId: function () {
                return tenantConfigurationId;
            },

            setConfigurationId: function (value) {
                tenantConfigurationId = value;
            },

            getElement: function (versionId, elementId, refresh, context) {
                var self = this, dfd = $.Deferred(), element;
                element = elementCache[elementId];
                if (element && !refresh) {
                    dfd.resolve(element);
                } else {
                    removeElementFromCache(elementId);
                    $.when(getElementFromServer(versionId, elementId, context)).done(function (jObj) {
                        var solution = null, solutionConfiguration = null, solutionConfigurations, solutionConfigurationDictionary;
                        if (jObj[elementId].typeId === otApp.WellKnownElementGuids.SolutionType) {
                            removeSolutions();
                            solution = jObj[elementId];
                        }

                        element = getElement(jObj, elementId);
                        updateParentOf(element);

                        if (solution && solution.typeId === otApp.WellKnownElementGuids.SolutionType) {
                            solutionConfigurationDictionary = self.getChildrenByTypeId(elementId, otApp.WellKnownElementGuids.ConfigurationDictionaryType);
                            if (solutionConfigurationDictionary[0]) {
                                solutionConfigurations = getChildrenInternal(solutionConfigurationDictionary[0].id);
                                solutionConfiguration = solutionConfigurations[0];
                                if (solutionConfigurations.length > 1) {
                                    throw ("Unexpected number of configuration elements received.  Expected 1 and received " + solutionConfigurations.length)
                                }
                            }

                            otApp.changeSetManager.addSolutionChangeSet(solution, solutionConfiguration, tenantScope);
                        }

                        dfd.resolve(element);
                    }).fail(function (reply) {
                        var error = otApp.buildError(reply);
                        dfd.reject(error);
                    });
                }

                return dfd.promise();
            },

            getSingleElement: function (versionId, elementId) {
                var self = this, dfd = $.Deferred(), element;

                $.when(getSingleElementFromServer(versionId, elementId)).done(function (jObj) {
                    var element = jObj[elementId];
                    dfd.resolve(element);
                }).fail(function (reply) {
                    var error = otApp.buildError(reply);
                    dfd.reject(error);
                });

                return dfd.promise();
            },

            onOpeningSolutionVersion : function () {
                removeSolutions();
            },
            
            getSolution: function (versionId, solutionId, refresh) {
                return otApp.solutionManager.getElement(versionId, solutionId, refresh);
            },

            getSolutionConfiguration: function (tenantContainerVersionId, solutionWorkspaceId, configurationScope) {
                var dfd = $.Deferred(), workspace;
                workspace = this.getElementById(solutionWorkspaceId);
                $.when(getSolutionConfiguration(tenantContainerVersionId, solutionWorkspaceId, configurationScope)).done(function (jObj) {
                    cacheConfigruationElements(jObj, workspace.definition.referencedSolutionId);
                    dfd.resolve();
                }).fail(function (reply) {
                    var error = otApp.buildError(reply);
                    dfd.reject(error);
                });

                return dfd.promise();
            },

            getFullTextSearchConfiguration: function (tenantContainerVersionId, solutionWorkspaceId) {
                let uri = getBaseUri() + 'Elements(' + tenantContainerVersionId + '.' + solutionWorkspaceId + ')/FullTextSearchConfiguration';
                let ftsConfigurations = ot_App.ajax({
                    type: "GET",
                    url: uri,
                    contentType: "application/json; charset=utf-8",
                    dataType: "json"
                });
                return ftsConfigurations;
            },

            getCongfigurationElementsByTypeId: function (solutionId, typeId) {
                var id, solutionConfigurationElements, result = [];

                solutionConfigurationElements = elementConfigurationCache[solutionId];
                for (id in solutionConfigurationElements) {
                    if (solutionConfigurationElements.hasOwnProperty(id)) {
                        if (solutionConfigurationElements[id].typeId === typeId) {
                            result.push(solutionConfigurationElements[id]);
                        }
                    }
                }

                return result;
            },

            getConfigurationElements: function (solutionId) {
                var id, solutionConfigurationElements, result = [];

                solutionConfigurationElements = elementConfigurationCache[solutionId];
                for (id in solutionConfigurationElements) {
                    if (solutionConfigurationElements.hasOwnProperty(id)) {
                        result.push(solutionConfigurationElements[id]);
                    }
                }

                return result;
            },
            
            getStripedConfigurationElement: function (solutionId) {
            	var configurationName = StripedSolutionConfigurationNamePrefix + currentUserTenantElement.id;
            	
                solutionConfigurationElements = elementConfigurationCache[solutionId];
                for (id in solutionConfigurationElements) {
                    if (solutionConfigurationElements.hasOwnProperty(id)) {
                    	if (solutionConfigurationElements[id].name === configurationName) {
                    		return solutionConfigurationElements[id];
                    	}                        
                    }
                }

                return null;            	
            },

            createStripedConfiguration: function(solutionId) {
                var self = this, dfd = $.Deferred(), productionConfiguration = this.getProductionConfiguration(solutionId), maxLength = 128;

                function getDisplayName(nameBasis) {
                	var displayName = nameBasis.format(currentUserTenantElement.name);
                	if (displayName.length > maxLength) {
                		return displayName.substr(0, maxLength)
                	}
                	
                	return displayName;                	
                }

                function getSolutionConfigurationDisplayName() {
                	return getDisplayName(Globalize.localize("admin.config.Striping.SolutionConfigurationDisplayName"));
                }

                $.when(self.getUUIDs(1)).done(function (ids) {
                    var solutionConfiguration = {};
                    solutionConfiguration.name = StripedSolutionConfigurationNamePrefix + currentUserTenantElement.id;
                    solutionConfiguration.displayName =  getSolutionConfigurationDisplayName(tenantElement.name);
                    solutionConfiguration.id = ids[1];
                    solutionConfiguration.typeId = otApp.WellKnownElementGuids.ConfigurationType;
                    solutionConfiguration.type = "Configuration";
                    solutionConfiguration.parentId = productionConfiguration.parentId;
                    solutionConfiguration.containerId = solutionId;
                    solutionConfiguration.definition = { tenantConfigurationId: currentUserTenantElement.usage.ownedConfigurationId };

                    var createdElements = [];
                    createdElements.push(solutionConfiguration);

                    $.when(self.executeBatchEx(null, createdElements, null, null)).done(function () {
                        dfd.resolve(solutionConfiguration);
                    }).fail(function (error) {
                        dfd.reject(error);
                    });
                }).fail(function (error) {
                    dfd.reject(error);
                });

                return dfd.promise();
            },

            getSolutionConfigurations: function (solutionId) {
                var configurations = this.getCongfigurationElementsByTypeId(solutionId, otApp.WellKnownElementGuids.ConfigurationType);
                return configurations;
            },

            getSolutionRoles: function (solutionId) {
                var roles = this.getCongfigurationElementsByTypeId(solutionId, otApp.WellKnownElementGuids.SolutionRolesType);
                if (roles.length > 0) {
                    return roles[0];
                }

                return null;
            },

            getSolutionArchivePolicy: function (solutionId) {
                var archivePolicies = this.getChildrenByTypeId(solutionId, ot_App.WellKnownElementGuids.ArchivePolicyConfigurationType);
                if (archivePolicies.length > 0) {
                    return archivePolicies[0];
                }
 
                return null;
            },

            getConfigurationSecurityPolicy: function (solutionId) {
                var policies = this.getCongfigurationElementsByTypeId(solutionId, otApp.WellKnownElementGuids.ConfigurationSecurityPolicyType);
                if (policies.length > 0) {
                    return policies[0];
                }

                return null;
            },

            getProductionConfiguration: function (solutionId) {
                var i, length, configurations = this.getSolutionConfigurations(solutionId);
                for (i = 0, length = configurations.length; i < length; i += 1) {
                    if (configurations[i].definition && configurations[i].definition.info && configurations[i].definition.info.isProduction) {
                        return configurations[i];
                    } 
                    
                    // Give it a second chance.  The definition node is absent if we do not have the proper permissions.
                    if (configurations[i].name === "Production") {
                        return configurations[i];
                    }
                }

                return null;
            },

            getVersionAvailabilityMap: function (solutionId, solutionConfigurationId) {
                var i, length, maps = this.getCongfigurationElementsByTypeId(solutionId, otApp.WellKnownElementGuids.VersionAvailabiltyMap);
                for (i = 0, length = maps.length; i < length; i += 1) {
                    if (maps[i].parentId === solutionConfigurationId) {
                        return maps[i];
                    }
                }

                return null;
            },

            // Returns the tenant element and populates the cache with all the tenant's children.   If
            // refresh is specified, the tenant is retrieved form the server even if it is already in cache.
            getTenant: function (refresh, context, tenantType) {
                var dfd = $.Deferred();

                if (tenantElement && !refresh) {
                    dfd.resolve(tenantElement);
                } else {
                    if (tenantElement) {
                        removeElementFromCache(tenantElement.id);
                    }

                    $.when(getTenant(context, tenantType)).done(function (jObj) {
                        getElement(jObj, null);
                        if (tenantType === "Organization") {
                        	currentUserTenantElement = tenantElement;
                        } 
                        
                        dfd.resolve(tenantElement);
                    }).fail(function (error) {
                        $('body').messenger({ text: error.message, type: "error" });
                        dfd.reject(error);
                    });
                }

                return dfd.promise();
            },

            sendBatchEx: function (databaseId, elementsCreated, elementsUpdated, elementsDeleted, useSyncCall) {
                var jsonObjects = [], i, length, dfd = $.Deferred(), deleteElement, containerId = null;

                if (elementsDeleted && elementsDeleted.length > 0) {
                    containerId = elementsDeleted[0].containerId;
                    for (i = 0, length = elementsDeleted.length; i < length; i += 1) {

                        deleteElement = {
                            operationType: "Delete",
                            id: elementsDeleted[i].id
                        };

                        if (elementsDeleted[i].containerVersionId === null) {
                            deleteElement.containerId = elementsDeleted[i].containerId;
                        } else {
                            deleteElement.containerVersionId = elementsDeleted[i].containerVersionId;
                        }

                        jsonObjects.push(deleteElement);
                    }
                }

                if (elementsCreated && elementsCreated.length > 0) {
                    containerId = elementsCreated[0].containerId;
                    for (i = 0, length = elementsCreated.length; i < length; i += 1) {
                        jsonObjects.push({ operationType: "Create", element: elementsCreated[i] });
                    }
                }

                if (elementsUpdated && elementsUpdated.length > 0) {
                    containerId = elementsUpdated[0].containerId;
                    for (i = 0, length = elementsUpdated.length; i < length; i += 1) {
                        jsonObjects.push({ operationType: "Update", element: elementsUpdated[i] });
                    }
                }

                $.when(processBatchEx(databaseId, jsonObjects, containerId, useSyncCall)).done(function (response) {
                    dfd.resolve(response, containerId);
                }).fail(function (error) {
                    dfd.reject(error);
                });

                return dfd.promise();
            },

            executeBatchEx: function (databaseId, elementsCreated, elementsUpdated, elementsDeleted, useSyncCall) {
                return this.sendBatchEx(databaseId, elementsCreated, elementsUpdated, elementsDeleted, useSyncCall)
                    .done(function (changeLog, containerId) {
                        var changeSet;
                        synchronizeElementsInCache(changeLog.changeEventInfos);
                        
                        changeSet = otApp.changeSetManager.getChangeSetByContainerId(containerId);
                        if (changeSet) {
                            otApp.changeSetManager.updateChangeSetTokens(elementCache[changeSet.owner.id], changeLog.changeTokens);
                        }
	                
                    	_.delay(function () {
							triggerChangeLogEvents(changeLog.changeEventInfos, true);
                    	}, 0);
                    });
            },

            // Requests the server to create the indicated element.
            // element: the element to create.
            // returns a promise that will be fulfilled once the element is created.
            newElement: function (element) {
                var self = this, dfd = $.Deferred(), createdElements = [], createdElement;

                function createIt() {
                    createdElements.push(element);
                    $.when(self.executeBatchEx(null, createdElements, null, null)).done(function () {
                        createdElement = self.getElementById(element.id);
                        dfd.resolve(createdElement);
                    }).fail(function (error) {
                        dfd.reject(error);
                    });
                }

                if (!element.id) {
                    $.when(self.getUUIDs(1)).done(function (ids) {
                        element.id = ids[0];
                        createIt();
                    }).fail(function (error) {
                        dfd.reject(error);
                    });
                } else {
                    createIt();
                }

                return dfd.promise();
            },

            // Requests the server to update the indicated element.
            // element: the element to update.
            // returns a promise that will be fulfilled once the element is updated.
            updateElement: function (element, useSyncCall) {
                var self = this, dfd = $.Deferred(), updatedElements, containerVersionId, updatedElement;

                updatedElements = [];

                updatedElements.push(element);

                if (element.containerVersionId) {
                    containerVersionId = element.containerVersionId;
                } else {
                    containerVersionId = element.containerId;
                }

                $.when(self.executeBatchEx(null, null, updatedElements, null, useSyncCall)).done(function () {
                    updatedElement = self.getElementById(element.id);
                    dfd.resolve(updatedElement);
                }).fail(function (error) {
                    if (containerVersionId === null) {
                        // Cannot restore the element.
                        dfd.resolve(element);
                    } else {
                        // Restore the element.
                        $.when(otApp.solutionManager.getElement(containerVersionId, element.id, true)).done(function () {
                            dfd.reject(error);
                        });
                    }
                });
                return dfd.promise();
            },

            // Requests the server to update the indicated elements.
            // elements: the elements to update.
            // returns a promise that will be fulfilled once the elements are updated.
            updateElements: function (containerVersionId, elements, useSyncCall) {
                var self = this, dfd = $.Deferred();

                $.when(self.executeBatchEx(null, null, elements, null, useSyncCall)).done(function () {
                    let updatedElements = [];
                    elements.forEach(element => updatedElements.push(self.getElementById(element.id)));
                    dfd.resolve(updatedElements);
                }).fail(function (error) {
                    if (containerVersionId === null) {
                        // Cannot restore the element.
                        dfd.resolve(elements);
                    } else {
                        // Restore the element.
                        let restoreElements = [];
                        elements.forEach(element => restoreElements.push(
                            $.when(otApp.solutionManager.getElement(containerVersionId, element.id, true))
                        ));
                        Promise.all(restoreElements).finally(function () {
                            dfd.reject(error);
                        });
                    }
                });
                return dfd.promise();
            },

            // Requests the server to delete the indicated element.
            // element: the element to delete.
            // returns a promise that will be fulfilled once the element is deleted.
            deleteElement: function (element) {
                var self = this, deletedElements;

                deletedElements = [element];
                return self.executeBatchEx(null, null, null, deletedElements);
            },

            sendBatch: function (databaseId, elementsCreated, elementsUpdated, elementsDeleted) {
                var i, prevContainerVersionId, length, batch, dfd = $.Deferred();

                prevContainerVersionId = null;
                batch = "<Package>";

                if (elementsCreated && elementsCreated.length > 0) {
                    prevContainerVersionId = elementsCreated[0].containerVersionId;
                    batch += "<Create ContainerVersionId='" + prevContainerVersionId + "'>";
                    for (i = 0, length = elementsCreated.length; i < length; i += 1) {
                        if (elementsCreated[i].containerVersionId === prevContainerVersionId) {
                            batch += elementsCreated[i].getPayload();
                            prevContainerVersionId = elementsCreated[i].containerVersionId;
                        } else {
                            batch += "</Create>";
                            prevContainerVersionId = elementsCreated[i].containerVersionId;
                            batch += "<Create ContainerVersionId='" + prevContainerVersionId + "'>";
                            batch += elementsCreated[i].getPayload();
                        }
                    }
                    batch += "</Create>";
                }

                if (elementsUpdated && elementsUpdated.length > 0) {
                    prevContainerVersionId = elementsUpdated[0].containerVersionId;
                    batch += "<Update ContainerVersionId='" + prevContainerVersionId + "'>";

                    for (i = 0, length = elementsUpdated.length; i < length; i += 1) {
                        if (elementsUpdated[i].containerVersionId === prevContainerVersionId) {
                            batch += elementsUpdated[i].getPayload();
                            prevContainerVersionId = elementsUpdated[i].containerVersionId;
                        } else {
                            batch += "</Update>";
                            prevContainerVersionId = elementsUpdated[i].containerVersionId;
                            batch += "<Update ContainerVersionId='" + prevContainerVersionId + "'>";
                            batch += elementsUpdated[i].getPayload();
                        }
                    }
                    batch += "</Update>";
                }

                if (elementsDeleted && elementsDeleted.length > 0) {
                    prevContainerVersionId = elementsDeleted[0].containerVersionId;
                    batch += "<Delete ContainerVersionId='" + prevContainerVersionId + "'>";

                    for (i = 0, length = elementsDeleted.length; i < length; i += 1) {
                        if (elementsDeleted[i].containerVersionId === prevContainerVersionId) {
                            batch += "<Id>";
                            batch += elementsDeleted[i].id;
                            batch += "</Id>";
                            prevContainerVersionId = elementsDeleted[i].containerVersionId;
                        } else {
                            batch += "</Delete>";
                            prevContainerVersionId = elementsUpdated[i].containerVersionId;
                            batch += "<Delete ContainerVersionId='" + prevContainerVersionId + "'>";
                            batch += "<Id>";
                            batch += elementsDeleted[i].id;
                            batch += "</Id>";
                        }
                    }

                    batch += "</Delete>";
                }

                batch += "</Package>";

                $.when(processBatch(databaseId, batch)).done(function () {
                    dfd.resolve();
                }).fail(function (error) {
                    dfd.reject(error);
                });

                return dfd.promise();
            },

            createElement: function (element) {
                var dfd = $.Deferred(), createdElements = [];

                function createIt() {
                    createdElements.push(element);
                    $.when(otApp.solutionManager.sendBatch(null, createdElements, null, null)).done(function () {
                        // Always roundtrip element.  This will change when the server implements an element change log.
                        $.when(otApp.solutionManager.getElement(element.containerVersionId, element.id)).done(function (newElement) {
                            dfd.resolve(newElement);
                        }).fail(function (error) {
                            dfd.reject(error);
                        });
                    }).fail(function (error) {
                        dfd.reject(error);
                    });
                }

                if (!element.id) {
                    $.when(this.getUUIDs(1)).done(function (ids) {
                        element.id = ids[0];
                        createIt();
                    }).fail(function (error) {
                        dfd.reject(error);
                    });
                } else {
                    createIt();
                }

                return dfd.promise();
            },

            update: function (element) {
                var dfd = $.Deferred(), updatedElements;

                // Configuration elements do not have a container version id but one is needed for the batch command.
                // Use the id of the first element in he parent change that has one.
                // All this will change once the server implements update.
                setContainerVersionId(element);

                updatedElements = [];

                updatedElements.push(element);

                $.when(otApp.solutionManager.sendBatch(null, null, updatedElements, null)).done(function () {
                    $.when(otApp.solutionManager.getElement(element.containerVersionId, element.id, true)).done(function (updatedElement) {
                        dfd.resolve(updatedElement);
                    }).fail(function (error) {
                        dfd.reject(error);
                    });
                }).fail(function (error) {
                    dfd.reject(error);
                });
                return dfd.promise();
            },

            remove: function (element) {
                var deletedElements;

                deletedElements = [element];
                return this.executeBatchEx(null, null, null, deletedElements);
            },

            removeElements: function (elements) {
                var i, deletedElements;

                deletedElements = [];
                for (i = 0; i < elements.length; i += 1) {
                    deletedElements.push(elements[i]);
                }

                return this.executeBatchEx(null, null, null, deletedElements);
            },

            getElementById: function (id) {
                var element = elementCache[id];
                if (element) {
                    return element;
                }

                return null;
            },

            getChildren: function (parentId, allLevels, sort) {
                return getChildrenInternal(parentId, allLevels, sort);
            },

            // Returns a list of the immediate children that match the type name.
            getImmediateChildrenByTypeName: function (parentId, typeName) {
                var children = [], i, length, allChildren = getChildrenInternal(parentId, false, true);
                for (i = 0, length = allChildren.length; i < length; i += 1) {
                    if (allChildren[i].type === typeName) {
                        children.push(allChildren[i]);
                    }
                }

                return children;
            },

            // Returns a list of the children that match the type name.
            getChildrenByTypeName: function (parentId, typeName) {
                var children = [], i, length, allChildren = getChildrenInternal(parentId, true, true);
                for (i = 0, length = allChildren.length; i < length; i += 1) {
                    if (allChildren[i].type === typeName) {
                        children.push(allChildren[i]);
                    }
                }

                return children;
            },

            // Returns a list of the immediate children that match the type identifier.
            getImmediateChildrenByTypeId: function (parentId, typeId) {
                var children = [], i, length, allChildren = getChildrenInternal(parentId, false, true);
                for (i = 0, length = allChildren.length; i < length; i += 1) {
                    if (allChildren[i].typeId === typeId) {
                        children.push(allChildren[i]);
                    }
                }

                return children;
            },

            // Returns a list of the children that match the type id.
            getChildrenByTypeId: function (parentId, typeId) {
                var children = [], i, length, allChildren = getChildrenInternal(parentId, true, true);
                for (i = 0, length = allChildren.length; i < length; i += 1) {
                    if (allChildren[i].typeId === typeId) {
                        children.push(allChildren[i]);
                    }
                }

                return children;
            },

            // checkout the solution version
            // versionId - the version id to check in
            // solutionId - the solution id of the version
            // version - the version obj that contains the version properties that changed (i.e., comment major/minor type)
            // Returns - nothing.
            checkOutVersion: function (versionId, solutionId, version) {
                var uri, processingCheckOut, jsonString;

                uri = getBaseUri() + "Elements(" + versionId + "." + solutionId + ")/Version?action=CheckOut" + appendTenantScope(true);

                jsonString = JSON.stringify(version);

                processingCheckOut = ot_App.ajax({
                    type: "POST",
                    url: uri,
                    data: jsonString,
                    contentType: "application/json; charset=utf-8",
                    dataType: "json"
                });

                return processingCheckOut.pipe(function (reply) {
                    return reply;
                }, function (reply) {
                    var error = otApp.buildError(reply);
                    return error;
                });
            },

            // check in the solution version
            // versionId - the version id to check in
            // solutionId - the solution id of the version
            // version - the version obj that contains the version properties that changed (i.e., comment major/minor type)
            // Returns - nothing.
            checkInVersion: function (versionId, solutionId, version) {
                var uri, processingCheckIn, jsonString;

                uri = getBaseUri() + "Elements(" + versionId + "." + solutionId + ")/Version?action=CheckIn" + appendTenantScope(true);

                jsonString = JSON.stringify(version);

                processingCheckIn = ot_App.ajax({
                    type: "POST",
                    url: uri,
                    data: jsonString,
                    contentType: "application/json; charset=utf-8",
                    dataType: "json"
                });

                return processingCheckIn.pipe(function (reply) {
                    return reply;
                }, function (reply) {
                    var error = otApp.buildError(reply);
                    return error;
                });
            },

            // delete the solution version
            // versionId - the version id to check in
            // solutionId - the solution id of the version
            // Returns - nothing.
            deleteVersion: function (versionId, solutionId) {
                var uri, processingDelete;

                uri = getBaseUri() + "Elements(" + versionId + "." + solutionId + ")/Version" + appendTenantScope(true);

                processingDelete = ot_App.ajax({
                    type: "DELETE",
                    url: uri,
                    data: null,
                    contentType: "application/json; charset=utf-8",
                    dataType: "json"
                });

                return processingDelete.pipe(function (reply) {
                    otApp.changeSetManager.removeChangeSet(solutionId);
                    removeElementFromCache(solutionId);
                    return reply;
                }, function (reply) {
                    var error = otApp.buildError(reply);
                    return error;
                });
            },

            // delete all solution versions and the solution workspace.
            // id - the workspace id
            // versionId - the version id of the solution.
            // solutionId - the solution id.
            // solutionWorkspaeId = the solution worksapce.
            // Returns - nothing.
            deleteAllVersions: function (versionId, solutionId, solutionWorkspaeId) {
                var uri, processingDelete;

                uri = getBaseUri() + "Elements(" + versionId + "." + solutionId + ")/Version?action=DeleteAllVersions" + appendTenantScope(true);

                processingDelete = ot_App.ajax({
                    type: "POST",
                    url: uri,
                    data: null,
                    contentType: "application/json; charset=utf-8",
                    dataType: "json"
                });

                return processingDelete.pipe(function (reply) {
                    // Remove solution workspace from cache.
                    removeElementFromCache(solutionWorkspaeId);
                    return reply;
                }, function (reply) {
                    var error = otApp.buildError(reply);
                    return error;
                });
            },
            
            publishSolution: function(versionId, solutionId) {
                return doAjax(getBaseUri() + "Elements(" + versionId + "." + solutionId + ")/Version?action=publish" + appendTenantScope(true),
                    "POST",
                    null);
            },

            // synchronize all EIS objects in the given solution version (in progress version) 
            // and assoicated with the given repository.
            // id - the workspace id
            // versionId - the version id of the solution.
            // solutionId - the solution id.
            // repositoryConnectionId = the repository connection id.
            // Returns - nothing.
            synchronizeWithRepository: function (versionId, solutionId, repositoryConnectionId) {
                var uri, processingCheckIn, parameters = {};

                uri = getBaseUri() + "Elements(" + versionId + "." + solutionId + ")/Version?action=SyncWithRepository" + appendTenantScope(true);

                parameters.repositoryConnectionId = repositoryConnectionId;

                processingCheckIn = ot_App.ajax({
                    type: "POST",
                    url: uri,
                    data: JSON.stringify(parameters),
                    contentType: "application/json; charset=utf-8",
                    dataType: "json"
                });

                return processingCheckIn.pipe(function (reply) {
					showInfoBox(Globalize.localize("admin.config.SynchronizeEisRepository"));
                    return reply;
                }, function (reply) {
                    var error = otApp.buildError(reply);
					showErrorBox(error);
                    return error;
                });
            },

            getProductionDatabases: function (tenantId) {
                var configurations, i, length;
                configurations = otApp.solutionManager.getChildrenByTypeName(tenantId, "TenantConfiguration");
                for (i = 0, length = configurations.length; i < length; i += 1) {
                    if (configurations[i].definition.isProduction) {
                        return configurations[i].definition.info.databases;
                    }
                }

                return [];
            },

            getUUIDs: function (howMany) {
                var ids, dfd = $.Deferred();

                if (uuidCache.length > howMany) {
                    ids = uuidCache.splice(0, howMany);
                    dfd.resolve(ids);
                } else {
                    $.when(getUniqueIdsFromServer(howMany)).done(function (uuids) {
                        uuidCache = uuids;
                        ids = uuidCache.splice(0, howMany);
                        dfd.resolve(ids);
                    }).fail(function (error) {
                        dfd.reject(error);
                    });
                }

                return dfd.promise();
            },

            upgrade: function (containerVersionId, containerId) {
                return upgradeSolution(containerVersionId, containerId);
            },

            isGlobalTenant: function () {
                return tenantScope === "Global";
            },
            
            getOrganizationRoles: function () {
                var gettingOrganizationRoles, uri;

                uri = getBaseUri() + "Roles";

                gettingOrganizationRoles = ot_App.ajax({
                    type: "GET",
                    url: uri,
                    data: "",
                    contentType: "application/xml; charset=utf-8",
                    dataType: "json"
                });

                return gettingOrganizationRoles.pipe(function (reply) {
                    return reply;
                }, function (reply) {
                    var error = otApp.buildError(reply);
                    return error;
                });
            },

            // create a new workspace and solution with the required child elements
            createWorkspace: function (workspace, tenant, databaseId) {
                var self, solution, createdElements, dfd = $.Deferred();
                self = this;
                createdElements = [];

                $.when(self.getUUIDs(2)).done(function (ids) {
                    // solution element
                    solution = new otApp.Element(otApp.WellKnownElementGuids.SolutionType, null);
                    solution.name = workspace.name;
                    solution.displayName = workspace.displayName;
                    solution.comment = workspace.comment;
                    solution.id = ids[0];
                    solution.containerId = solution.id;
                    createdElements.push(solution);

                    // workspace element
                    workspace.id = ids[1];
                    workspace.definition = { referencedSolutionId: solution.id };
                    createdElements.push(workspace);

                    $.when(self.executeBatchEx(databaseId, createdElements, null, null)).done(function () {
                        dfd.resolve(tenant.id, workspace.id, solution.id);
                    }).fail(function (error) {
                        dfd.reject(error);
                    });
                }).fail(function (error) {
                    dfd.reject(error);
                });

                return dfd.promise();
            },

            // create a new workspace and solution with the required child elements
            createWorkspaceAndSolution: function (workspace, solution, databaseId) {
                var self, createdElements, dfd = $.Deferred(), newElement;
                self = this;
                createdElements = [];

                $.when(self.getUUIDs(2)).done(function (ids) {
                    // solution element
                    solution.name = workspace.name;
                    solution.displayName = workspace.displayName;
                    solution.comment = workspace.comment;
                    solution.id = ids[0];
                    solution.containerId = solution.id;
                    createdElements.push(solution);

                    // workspace element
                    workspace.id = ids[1];
                    workspace.definition = { referencedSolutionId: solution.id };
                    createdElements.push(workspace);

                    $.when(self.executeBatchEx(databaseId, createdElements, null, null)).done(function () {
                        newElement = self.getElementById(workspace.id);
                        dfd.resolve(newElement);
                    }).fail(function (error) {
                        dfd.reject(error);
                    });
                }).fail(function (error) {
                    dfd.reject(error);
                });

                return dfd.promise();
            },

            setMode: function (uriMode) {
                if (uriMode === "test") {
                    mode = "test";
                } else {
                    mode = "production";
                }
            },

            setBaseUri: function (value) {
                if (value) {
                    serviceUrl = value;
                }
            },

            getBaseUri: function () {
                return getBaseUri();
            },

            // import a new solution.
            // containerVersionId - The tenant containerVwersionId.
            // folderId - the id of the folder.
            // domFileInputForm - if file upload form element (DOM) that contains
            //                    the file input element of the file to upload. This may be null or undefined. 
            // databaseId - the id of the database used for the new solution
            // return promise object- It will resolve with `elementInfo` or fail with `error` object.
            importSolution: function (containerVersionId, folderId, domFileInputForm, databaseId) {
                var restUri, ajaxOptions, importSolutionElement, postingSolutionElement;
                restUri = getBaseUri() + "Elements(" + containerVersionId + "." + folderId +
                    ")/Import?mode=Deploy&include=Definition&databaseId=" + databaseId + appendTenantScope(true);
                importSolutionElement = $.Deferred();
                ajaxOptions = buildFileUploadAjaxSettings(restUri, null, domFileInputForm, null, "POST");

                if (ajaxOptions === null) {
                    ajaxOptions = {
                        url: restUri,
                        data: null,
                        contentType: "application/xml; charset=utf-8",
                        dataType: "json",
                        type: "POST"
                    };

                    postingSolutionElement = ot_App.ajax(ajaxOptions);
                } else if (ajaxOptions.iframe !== undefined && ajaxOptions.iframe === true) {
                    postingSolutionElement = ot_App.ajax(ajaxOptions.uri, ajaxOptions);
                } else {
                    ajaxOptions.xhr = buildFileUploadProgressReporter(importSolutionElement);
                    postingSolutionElement = ot_App.ajax(ajaxOptions);
                }

                postingSolutionElement.done(function (reply) {
                    importSolutionElement.resolve(reply);
                });

                postingSolutionElement.fail(function (reply) {
                    if (reply.statusText) {
                        $('body').messenger({ text: reply.statusText });
                    }
                    importSolutionElement.reject(reply);
                });

                return importSolutionElement.promise();
            },

            // import an existing solution version.
            // containerVersionId - The solution container version Id.
            // solutionId - the id of the solution.
            // domFileInputForm - if file upload form element (DOM) that contains
            //                    the file input element of the file to upload. This may be null or undefined. 
            // return promise object- It will resolve with `elementInfo` or fail with `error` object.
            importSolutionVersion: function (containerVersionId, solutionId, domFileInputForm) {
                var restUri, ajaxOptions, importSolutionElement, postingSolutionElement;

                restUri = getBaseUri() + "Elements(" + containerVersionId + "." + solutionId + ")?mode=Deploy" + appendTenantScope(true);

                importSolutionElement = $.Deferred();
                ajaxOptions = buildFileUploadAjaxSettings(restUri, null, domFileInputForm, null, "POST");

                if (ajaxOptions === null) {
                    ajaxOptions = {
                        url: restUri,
                        data: null,
                        contentType: "application/xml; charset=utf-8",
                        dataType: "text",
                        type: "POST"
                    };

                    postingSolutionElement = ot_App.ajax(ajaxOptions);
                } else if (ajaxOptions.iframe !== undefined && ajaxOptions.iframe === true) {
                    postingSolutionElement = ot_App.ajax(ajaxOptions.uri, ajaxOptions);
                } else {
                    ajaxOptions.xhr = buildFileUploadProgressReporter(importSolutionElement);
                    postingSolutionElement = ot_App.ajax(ajaxOptions);
                }

                postingSolutionElement.done(function (reply) {
                    importSolutionElement.resolve(reply);
                });

                postingSolutionElement.fail(function (reply) {
                    if (reply.statusText) {
                        $('body').messenger({ text: reply.statusText });
                    }
                    importSolutionElement.reject(reply);
                });

                return importSolutionElement.promise();
            },

            // export an existing solution version.
            // containerVersionId - The solution container version Id.
            // solutionId - the id of the solution.
            // return promise object- It will resolve with xml or fail with `error` object.
            exportSolutionVersion: function (containerVersionId, solutionId) {
                var uri;
                uri = getBaseUri() + "Elements(" + containerVersionId + "." + solutionId + ")/Version?action=Download&overwriteFormat=text" + appendTenantScope(true);
                $.fileDownload(uri, { httpMethod: "GET" });
            },
            
            downloadIHubDataDesignFile: function(containerVersionId, solutionId,entities) {
				 var uri = getBaseUri() + "Elements(" + containerVersionId + "." + solutionId + ")/Version?action=iHubDataObjectDesign&overwriteFormat=text";
				
				 ot_App.filedownload(uri, {
					 httpMethod: "POST",
					 data: entities == null ? "": "key=" + JSON.stringify(entities)
				 });
			 },
          
            downloadiHubSolutionVersion:  function (containerVersionId, solutionId) {
                var restUri = getBaseUri() + "Elements(" + containerVersionId + "." + solutionId + ")/Version?action=iHubDownload&overwriteFormat=text";
                var filedownloadResponse = ot_App.filedownload(restUri);
                filedownloadResponse.fail(function (reply) {
                     var errorObj = otApp.buildError($(reply).text());
                      $('body').messenger({ error: errorObj});
                });
                return filedownloadResponse.promise();
            },

            getSolutionVersionUrl: function (containerVersionId, solutionId) {
                var uri;
                uri = "Elements(" + containerVersionId + "." + solutionId + ")?childLevels=all&include=usage,definition&childDetails=true" + appendTenantScope(true);
                return uri;
            },
			
			getSolutionsAndEntities: function(containerVersionId, solutionId){
				var restUri = getBaseUri() + "Elements(" + containerVersionId + "." + solutionId + ")/Version?action=entities&overwriteFormat=text";
				ajaxOptions = {
					url: restUri,
					type: "GET",
					dataType: "json"
				}
				return ot_App.ajax(ajaxOptions);
			},
			
			 loadBusinessIdentifiers: function(containerVersionId, solutionId) {
				var restUri = getBaseUri() + "Elements(" + containerVersionId + "." + solutionId + ")/Version?action=getBusinessIdentifiers&overwriteFormat=text";
				ajaxOptions = {
					url: restUri,
					type: "GET",
					dataType: "json"
				}
				return ot_App.ajax(ajaxOptions);
			 },
			 
			 getAdminUIHideFlag: function(featureToggle, callback) {
				var restUri = getBaseUri() + "AdminUIFeatureToggle/"+ featureToggle;
				return ot_App.ajax({
					async: false,
					url: restUri,
					type: "GET",
					dataType: "json",
					success: function(response) {
						callback(response);
					}
				});
			},
			
			getAutoLogoutDuration: function(callback) {
				var restUri = getBaseUri() + "AdminUIFeatureToggle/AutoLogoutTime";
				return ot_App.ajax({
					async: false,
					url: restUri,
					type: "GET",
					dataType: "json",
					success: function(response) {
						callback(response);
					}
				});
			},
			
            removeElementFromCache: function (elementId) {
                removeElementFromCache(elementId);
            },

            // Returns an array containing all known solution elements.
            getSolutions: function () {
                var solutions = [];
                $.each(solutionCache, function (solutionCacheEntryId) {
                    solutions.push(solutionCache[solutionCacheEntryId]);
                });

                return solutions;
            },

            // Returns an array of element type elements for all those types that are marked as building block dictionaries.
            getBuildingBlockTypes: function () {
                return getTypesForCategory(builderElementCategory.buildingBlockDictionary);
            },

            // Returns an array of element type elements for all those types that are marked as options.
            getOptionTypes: function () {
                return getTypesForCategory(builderElementCategory.option);
            },

            // Returns an array of element type elements for all those types that are marked as services.
            getServicesTypes: function () {
                return getTypesForCategory(builderElementCategory.services);
            },

            // Returns all the elements in the specified solution that are of the given type.
            // If no solutionId is specified, the matching elements from all solutions are returned.
            getElements: function (typeId, solutionId) {
                var theSolution, elements = [], types, solutions = [], i, length, j, length1;
                if (solutionId) {
                    theSolution = solutionCache[solutionId];
                    if (theSolution && theSolution.typeId === otApp.WellKnownElementGuids.SolutionType) {
                        solutions.push(theSolution);
                    } else {
                        // We were given a bad solution id.
                        solutions = solutionCache;
                    }
                } else {
                    solutions = solutionCache;
                }

                for (i = 0, length = solutions.length; i < length; i += 1) {
                    types = this.getChildrenByTypeId(solutions[i].id, typeId);
                    for (j = 0, length1 = types.length; j < length1; j += 1) {
                        elements.push(types[j]);
                    }
                }

                return elements;
            },

            getTypes: function(id, criteria) {
                var allElements, elements, i, j, deferred = $.Deferred();
                allElements = [];
                    for (i = 0; i < criteria.length; i = i + 1) {
                        elements = this.getImmediateChildrenByTypeName(id, criteria[i]);
                        for (j = 0; j < elements.length; j = j + 1) {
                            allElements.push(elements[j]);
                        }
                    }
                return deferred.resolve(allElements);

            },
            
            findElements: function (options) {
            	var self = this;
                if (!options) {
                    options = {};
                }

                var deferred = $.Deferred();

                this.getElement(options.versionId, options.elementId, options.refresh, options.context).done(function (element) {
                    var elements = findElements(elementCache, options);
                    if (element.type === "ViewDictionary") {
                    	injectViews(self, elements, element.containerId);
                    }
                    
                    deferred.resolve(elements);
                }).fail(deferred.reject);

                return deferred.promise();
            },

            setActiveConfiguration: function (newSolutionConfigurationId) {
                otApp.changeSetManager.addSolutionConfigurationChangeSet(elementCache[newSolutionConfigurationId], tenantScope);
            },

            // deletes the tenat configuration and all the databases.
            // element: the tenant configuration to delete.
            // returns a promise that will be fulfilled once the element is deleted.
            deleteTenantConfiguration: function (element) {
                var self = this, deletedElements, dbElement, i, length;
                deletedElements = [];

                deletedElements.push(element);
                length = element.definition.info.databases.length;
                for (i = 0; i < length; i = i + 1) {
                    dbElement = this.getElementById(element.definition.info.databases[i].id);
                    deletedElements.push(dbElement);
                }

                return self.executeBatchEx(null, null, null, deletedElements);
            },

            applyChangeSetChanges: function (changeSetOwnerId, changeEventInfos) {
                synchronizeElementsInCache(changeEventInfos);
				triggerChangeLogEvents(changeEventInfos, false);
                return elementCache[changeSetOwnerId];
            },
            
            // Gets the global tenant element.  
            getUser: function() {
            	return otApp.itemManager.getUser();
            },
            
            // auoto correct errors in a solution.
            // containerVersionId - The containerVwersionId.
            // solutionId - the id of the solutionr.
            // toDos - the array of to do elements
            // return promise object- It will resolve with `elementInfo` or fail with `error` object.
            autoFix: function (containerVersionId, solutionId, toDos) {
                var uri, autoFixSolution, jsonString, changeSet;

                uri = getBaseUri() + "Elements(" + containerVersionId + "." + solutionId + ")/ToDo?action=AutoCorrect&changeLog=true" + appendTenantScope(true);

                jsonString = JSON.stringify(toDos);

                autoFixSolution = ot_App.ajax({
                    type: "POST",
                    url: uri,
                    data: jsonString,
                    contentType: "application/json; charset=utf-8",
                    dataType: "json"
                });

                return autoFixSolution.pipe(function (changeLog) {
                    synchronizeElementsInCache(changeLog.changeEventInfos);
                    
                    changeSet = otApp.changeSetManager.getChangeSetByContainerId(solutionId);
                    if (changeSet) {
                        otApp.changeSetManager.updateChangeSetTokens(elementCache[changeSet.owner.id], changeLog.changeTokens);
                    }

                    triggerChangeLogEvents(changeLog.changeEventInfos, true);
                    
                    return changeLog;
                }, function (reply) {
                    var error = otApp.buildError(reply);
                    return error;
                });
            },
            
            cleanCache: function () {
				otApp.changeSetManager.reset();
				elementCache = {};
				uuidCache = [];
				solutionCache = {};
				elementTypeCache = {};
				elementConfigurationCache = {};
				tenantElement = null;
				tenantConfigurationId = null;
            }
        };
    }

    solutionManagerSingleton = init();

    otApp.solutionManager = solutionManagerSingleton;

    // Possible versions state.
    solutionManagerSingleton.versionState = {
        "Available": 0,
        "Reserved": 1,
        "InProgress": 2
    };

    // This enumeration lists the valid values for element category.
    solutionManagerSingleton.builderElementCategory = {
        "none": 0,
        "option": 1,
        "buildingBlockDictionary": 2,
        "services": 3
    };

    solutionManagerSingleton.versionAvailabilityOption = {
        "Available": 0,
        "AvailableReadOnly": 3,
        "Unavailable": 1,
        "Disabled": 2
    };

    solutionManagerSingleton.logicalDatabaseType = {
        "allInOne": 0,
        "objectAndIntelligence": 1,
        "allSeparate": 2
    };

    return solutionManagerSingleton;

}(ot_App));

(function (otApp) {
    var changeSetManagerSingleton, changeSetOwnerType;

    changeSetOwnerType = {
        "tenant": 0,
        "solution": 1,
        "configuration": 2
    };

    function init() {
        var knownChangeSets = {}, pollTimer, pollWait = 5000;

        function getChangeSetByOwnerId(changeSetOwnerId) {
            return knownChangeSets[changeSetOwnerId];
        }

        function getOrAddChangeSet(changeSetOwner) {
            var changeSet;

            changeSet = knownChangeSets[changeSetOwner.id];

            if (!changeSet) {
                changeSet = {};
                knownChangeSets[changeSetOwner.id] = changeSet;
            }

            changeSet.owner = changeSetOwner;

            return changeSet;
        }

        function removeChangeSetByOwnerId(changeSetOwnerId) {
            if (knownChangeSets[changeSetOwnerId]) {
                delete knownChangeSets[changeSetOwnerId];
            }
        }

        function getChangeLogUri(changeSet) {
            var uri = otApp.solutionManager.getBaseUri() + "Elements(";
            if (changeSet.owner.typeId === otApp.WellKnownElementGuids.ConfigurationType) {
                uri += changeSet.owner.containerId + "." + changeSet.solutionConfigurationId + ")/ChangeLog";
                uri += "?configurationId=" + changeSet.tenantConfigurationId;
                uri +=  "&tenantScope=" + changeSet.tenantScope;
            } else {
                uri += changeSet.owner.containerVersionId + "." + changeSet.owner.id + ")/ChangeLog";
                if (changeSet.owner.typeId === otApp.WellKnownElementGuids.SolutionType && changeSet.solutionConfigurationId) {
                    uri += "?configurationId=" + changeSet.tenantConfigurationId;
                    uri +=  "&tenantScope=" + changeSet.tenantScope;
                } else {
                    uri +=  "?tenantScope=" + changeSet.tenantScope;
                }
            }

            return uri;
        }

        function getChangeLog(changeSetOwner) {
            var gettingChangeLog, uri;

            uri = getChangeLogUri(changeSetOwner);

            gettingChangeLog = ot_App.ajax({
                type: "GET",
                url: uri,
                data: "",
                contentType: "application/json; charset=utf-8",
                dataType: "json"
            });

            return gettingChangeLog;
        }

        function getChangeSetDifferences(changeSet) {
            var gettingChangeSetDifferences, children, i, length, info = {}, solutionConfigurationElements, uri;

            if (changeSet.owner.typeId !== otApp.WellKnownElementGuids.ConfigurationType) {
                children = otApp.solutionManager.getChildren(changeSet.owner.id, true, false);
                for (i = 0, length = children.length; i < length; i += 1) {
                    info[children[i].id] = children[i].changeId;
                }

                info[changeSet.owner.id] = changeSet.owner.changeId;
            } else {
                solutionConfigurationElements = otApp.solutionManager.getConfigurationElements(changeSet.owner.containerId);
                for (i = 0, length = solutionConfigurationElements.length; i < length; i += 1) {
                    info[solutionConfigurationElements[i].id] = solutionConfigurationElements[i].changeId;
                }
            }

            uri = getChangeLogUri(changeSet);

            gettingChangeSetDifferences = ot_App.ajax({
                type: "POST",
                url: uri,
                data: JSON.stringify(info),
                contentType: "application/json; charset=utf-8",
                dataType: "json"
            });

            return gettingChangeSetDifferences;
        }

        function isChangeSetModified(changeSet, changeTokenEntries) {
            var definitionChange = false, configurationChange = false;
            _.each(changeTokenEntries, function (changeTokenEntry) {
                if (changeTokenEntry.containerVersionId && changeTokenEntry.containerId === changeSet.owner.containerId) {
                    if (changeTokenEntry.changeToken !== changeSet.changeToken) {
                        // We have a definition change.
                        definitionChange = true;
                    }
                } else if (changeTokenEntry.containerId === changeSet.owner.containerId) {
                    if (changeTokenEntry.changeToken !== changeSet.configurationChangeToken) {
                        // We have a configuration change.
                        configurationChange = true;
                    }
                }
            });

            return definitionChange || configurationChange;
        }

        function updateChangeSet(changeSet, changeSetOwner, changeTokens) {
            _.each(changeTokens, function (changeTokenEntry) {
                if (changeTokenEntry.containerVersionId && changeTokenEntry.containerId === changeSet.owner.containerId) {
                    // We have a definition change token, update the token.
                    changeSet.changeToken = changeTokenEntry.changeToken;
                    changeSet.owner = changeSetOwner;
                } else if (changeTokenEntry.containerId === changeSet.owner.containerId) {
                    // We have a configuration change token, update the token.
                    changeSet.configurationChangeToken = changeTokenEntry.changeToken;
                    changeSet.owner = changeSetOwner;
                }
            });
        }

        function getAndApplyLatestChanges(changeSet) {
            var dfd = $.Deferred(), gettingChangeSetDifferences;

            gettingChangeSetDifferences = getChangeSetDifferences(changeSet);

            gettingChangeSetDifferences.done(function (changeLog) {
                // Apply change log.
                var changeSetOwner = otApp.solutionManager.applyChangeSetChanges(changeSet.owner.id, changeLog.changeEventInfos);
                updateChangeSet(changeSet, changeSetOwner, changeLog.changeTokens);
                dfd.resolve();
            });

            gettingChangeSetDifferences.fail(function (reply) {
                dfd.reject(otApp.buildError(reply));
            });

            return dfd.promise();
        }

        function checkChangeSet(changeSet) {
            var promise, dfd, gettingChangeLog;
            if (changeSet.changeToken === null || changeSet.configurationChangeToken === null) {
                // We are surely out of date with respect to the server.
                promise = getAndApplyLatestChanges(changeSet);
            } else {
                dfd = $.Deferred();
                gettingChangeLog = getChangeLog(changeSet);

                gettingChangeLog.done(function (reply) {
                    var changeSetIsModified, gettingAndApplyLatestChanges;
                    changeSetIsModified = isChangeSetModified(changeSet, reply.changeTokens);

                    if (changeSetIsModified) {
                        gettingAndApplyLatestChanges = getAndApplyLatestChanges(changeSet);
                        gettingAndApplyLatestChanges.done(function () {
                            $(window).trigger({ type: "serverStateChanged", changeSetOwnerType: changeSet.ownerType, id: changeSet.owner.id });
                            dfd.resolve();
                        });

                        gettingAndApplyLatestChanges.fail(function (reply1) {
                            dfd.reject(otApp.buildError(reply1));
                        });
                    } else {
                        dfd.resolve();
                    }
                });
                gettingChangeLog.fail(function (reply) {
                    dfd.reject(otApp.buildError(reply));
                });

                promise = dfd.promise();
            }

            return promise;
        }
        
        function pollForChanges() {
            var progressStatus = otApp.isBusyOverLay();
			otApp.setBusyOverLay(true);
            var changeSet, id, promises = [];
            for (id in knownChangeSets) {
                if (knownChangeSets.hasOwnProperty(id)) {
                    changeSet = knownChangeSets[id];
                    promises.push(checkChangeSet(changeSet));
                }
            }
            $.when.apply($(window), promises).then(function () {
                pollTimer = window.setTimeout(pollForChanges, pollWait);
            });
            otApp.setBusyOverLay(progressStatus);
        }

        function initializePollTimer() {
            if (!pollTimer) {
                // We do not have a timer yet, create it.
                pollTimer = window.setTimeout(pollForChanges, pollWait);
            }
        }
        
        function addChangeSetForSolutionConfiguration(configuration, tenantScope) {
            var changeSet;

            if (configuration.definition) {
                changeSet = getOrAddChangeSet(configuration);
                changeSet.ownerType = changeSetOwnerType.configuration;
                changeSet.configurationChangeToken = configuration.definition.info.changeToken;
                changeSet.solutionConfigurationId = configuration.id;
                changeSet.tenantConfigurationId = configuration.definition.tenantConfigurationId;
                changeSet.tenantScope = tenantScope;

                initializePollTimer();
            }
        }
        
        function getCurrentSolutionConfigurationChangeSet() {
            var solutionConfigurationChanget;
            $.each(knownChangeSets, function (changeSetOwnerId) {
                if (knownChangeSets[changeSetOwnerId].ownerType === changeSetOwnerType.configuration) {
                    solutionConfigurationChanget = knownChangeSets[changeSetOwnerId].owner;
                    return false;
                }

                return true;
            });

            return solutionConfigurationChanget;
        }
        
        function clearAll(keepTenant) {
            //// Note that changeset for global tenant will not be removed, unless otherwise specified.
            $.each(knownChangeSets, function (changeSetOwnerId) {
                if (!keepTenant || knownChangeSets[changeSetOwnerId].ownerType !== changeSetOwnerType.tenant) {
                    removeChangeSetByOwnerId(changeSetOwnerId);
                }
            });
        }

        return {

            addTenantChangeSet: function (tenant, tenantScope) {
                var changeSet;

                changeSet = getOrAddChangeSet(tenant);
                changeSet.ownerType = changeSetOwnerType.tenant;
                changeSet.changeToken = tenant.definition.info.changeToken;
                changeSet.tenantConfigurationId = null;
                changeSet.tenantScope = tenantScope;

                initializePollTimer();
            },

            addSolutionChangeSet: function (solution, configuration, tenantScope) {
                var changeSet;
                
                if (solution.definition) {
	                clearAll(true);
	                
	                changeSet = getOrAddChangeSet(solution);
	                changeSet.changeToken = solution.definition.info.changeToken;
	                changeSet.ownerType = changeSetOwnerType.solution;
                        changeSet.tenantScope = tenantScope;

	                if (configuration) {
	                    changeSet.configurationChangeToken = configuration.definition.info.changeToken;
	                    changeSet.solutionConfigurationId = configuration.id;
	                    changeSet.tenantConfigurationId = configuration.definition.tenantConfigurationId;
	                }
	
	                initializePollTimer();
                }
            },

            addSolutionConfigurationChangeSet: function (newSolutionConfiguration, tenantScope) {
                var currentSolutionConfigurationChangeSet;
                currentSolutionConfigurationChangeSet = getCurrentSolutionConfigurationChangeSet();
                if (newSolutionConfiguration && currentSolutionConfigurationChangeSet && 
                    newSolutionConfiguration.id === currentSolutionConfigurationChangeSet.id) {
                    return;
                }

                /// <summary>ChangeSet manager tracks change set for only one solution configuration.</summary>
                if (newSolutionConfiguration) {
                    clearAll(true);
                    addChangeSetForSolutionConfiguration(newSolutionConfiguration, tenantScope);
                }
            },

            getChangeSet: function (changeSetOwnerId) {
                getChangeSetByOwnerId(changeSetOwnerId);
            },

            removeChangeSet: function (changeSetOwnerId) {
                removeChangeSetByOwnerId(changeSetOwnerId);
            },

            getChangeSetByContainerId: function (containerId) {
                var changeSet;
                $.each(knownChangeSets, function (changeSetOwnerId) {
                    if (knownChangeSets[changeSetOwnerId].owner.containerId === containerId) {
                        changeSet = knownChangeSets[changeSetOwnerId];
                        return false;
                    }
                    return true;
                });

                return changeSet;
            },

            removeChangeSetByContainerId: function (containerId) {
                removeChangeSetByOwnerId(containerId);
                $.each(knownChangeSets, function (changeSetOwnerId) {
                    if (knownChangeSets[changeSetOwnerId].owner.containerId === containerId) {
                        removeChangeSetByOwnerId(changeSetOwnerId);
                    }
                });
            },

            updateChangeSetTokens: function (changeSetOwner, changeTokens) {
                var changeSet;
                changeSet = getChangeSetByOwnerId(changeSetOwner.id);
                if (changeSet) {
                    updateChangeSet(changeSet, changeSetOwner, changeTokens);
                }
            },

            clearAll: function () {
            	this.pausePolling();
                //// Note that changeset for global tenant will not be removed.
                clearAll(true);
            },

            reset: function () {
            	this.pausePolling();
            	clearAll(false);
            },
            
            pausePolling: function () {
                if (pollTimer) {
                    window.clearTimeout(pollTimer);
                    pollTimer = null;
                }
            },

            resumePolling: function () {
                pollTimer = window.setTimeout(pollForChanges, pollWait);
            }
        };
    }

    changeSetManagerSingleton = init();
    changeSetManagerSingleton.changeSetOwnerType = changeSetOwnerType;
    otApp.changeSetManager = changeSetManagerSingleton;
}(ot_App));

