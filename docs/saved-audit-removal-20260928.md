# Remove Saved audit from job Overview

Removed the Saved audit section, its Run audit button, missing-count badge and unused summary rendering from the job-card Overview at the user's request. No replacement panel was added. Requirements retains its explicit Check files action; audit tools and saved audit data are unchanged.

UI simplification guidance kept this scoped to removing the unwanted section without deleting underlying capability. The production-renderer division-tab regression checks that the section is absent and the Requirements file check remains.

Included in the 1.8.23 update; not present in 1.8.22.
