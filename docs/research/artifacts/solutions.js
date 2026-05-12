(function () {
    AdminConfig.Models.Solutions = Backbone.Model.extend({
        defaults: {
            orgType: "Organization",
            solutions: []
        },

        initialize: function () {
            ot_App.solutionManager.setBaseUri(ADMIN.serviceUrl);
        },

        sync: function (method, originalModel, originalOptions) {
            if (method !== "read") {
                return this._super.apply(this, arguments);
            }
            var dfd = $.Deferred(),
                success = originalOptions.success,
                error = originalOptions.error,
                tenant;

            ot_App.solutionManager.getTenant(true, null, originalModel.get("orgType")).done(function (resp) {
                if (success) {
                    success(resp);
                }

                tenant = resp;

                var excludedSolutions = [
                    ot_App.WellKnownElementGuids.SystemSolution,
                    ot_App.WellKnownElementGuids.SystemServicesSolution
                ];

                var showHiddenSolutionsOption = otUtils.getQueryParam(window.location.href, "showHiddenSolutions") || "false";
                if (showHiddenSolutionsOption.replace('#', '') !== "true") {
                    excludedSolutions.push(ot_App.WellKnownElementGuids.OpenTextEntityInstanceSecuritySolution);
                }

                var solutions = ot_App.solutionManager.getChildrenByTypeId(tenant.id, ot_App.WellKnownElementGuids.SolutionWorkspaceType);
                solutions = solutions.filter(function (solution) {
                    return excludedSolutions.indexOf(solution.definition.referencedSolutionId) === -1;
                });

                // Get solutions here
                originalModel.set("solutions", solutions);

                dfd.resolve(originalModel, resp, originalOptions);
            }).fail(function (resp) {
                if (error) {
                    error(resp);
                }

                dfd.reject(originalModel, resp, originalOptions);
            });

            return dfd.promise();
        }
    });
})();
