"""Tests for GET /projects and POST /project/set."""

from unittest.mock import AsyncMock, patch

from store.domain import SessionState


class TestProjectsEndpoint:
    async def test_list_projects(self, client, auth_headers, tmp_path):
        # Create fake project dirs
        (tmp_path / "project-a").mkdir()
        (tmp_path / "project-b").mkdir()
        (tmp_path / ".hidden").mkdir()  # should be excluded

        with patch("api.routes.projects.REPOS_ROOT", tmp_path):
            resp = await client.get("/projects", headers=auth_headers)

        assert resp.status_code == 200
        projects = resp.json()
        assert "project-a" in projects
        assert "project-b" in projects
        assert ".hidden" not in projects

    async def test_list_projects_requires_auth(self, client):
        resp = await client.get("/projects")
        assert resp.status_code == 422

    async def test_set_project(self, client, auth_headers, tmp_path):
        (tmp_path / "myproject").mkdir()

        with (
            patch("api.routes.projects.REPOS_ROOT", tmp_path),
            patch("api.routes.projects.validate_path", return_value=tmp_path / "myproject"),
            patch(
                "services.session.ensure_session",
                new_callable=AsyncMock,
                return_value=SessionState(),
            ),
            patch("services.session.update_state", new_callable=AsyncMock),
        ):
            resp = await client.post(
                "/project/set",
                json={"name": "myproject", "session_id": "default"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["active_project"] == "myproject"

    async def test_set_project_traversal_rejected(self, client, auth_headers):
        from tools.safety import SecurityError

        with patch(
            "api.routes.projects.validate_path",
            side_effect=SecurityError("Path outside ~/repos"),
        ):
            resp = await client.post(
                "/project/set",
                json={"name": "../../etc", "session_id": "default"},
                headers=auth_headers,
            )

        assert resp.status_code == 400

    async def test_set_project_not_found(self, client, auth_headers, tmp_path):
        with patch(
            "api.routes.projects.validate_path",
            return_value=tmp_path / "nonexistent",
        ):
            resp = await client.post(
                "/project/set",
                json={"name": "nonexistent", "session_id": "default"},
                headers=auth_headers,
            )

        assert resp.status_code == 404
