import logging as log

from gitlab import DEVELOPER_ACCESS
from gitlab.exceptions import GitlabError, GitlabCreateError
from .students import enrolled_students
from .course import InvalidCourse, create_solutions_group


def create_tag(project, tag, ref):
    """Creates protected tag on ref

    The tag is used by the abgabesystem to mark the state of a solution at the
    deadline.

    Args:
        project: GIT repository to create the tag in
        tag: name of the tag to be created
        ref: name of the red (branch / commit) to create the new tag on
    """

    print('Project %s. Creating tag %s' % (project.path, tag))

    project.tags.create({
        'tag_name': tag,
        'ref': ref
    })


def fork_reference(gl, reference, namespace, deploy_key):
    """Create fork of solutions for student.

    Returns the created project.

    Args:
        gl: gitlab API object
        reference: project to fork from
        namespace: namespace to place the created project into
        deploy_key: will be used by the abgabesystem to access the created
                    project
    """

    fork = reference.forks.create({
        'namespace': namespace.id
    })
    project = gl.projects.get(fork.id)
    project.visibility = 'private'
    project.container_registry_enabled = False
    project.lfs_enabled = False
    deploy_key = project.keys.create({
        'title': "Deploy Key",
        'key': deploy_key
    })
    project.keys.enable(deploy_key.id)
    project.save()

    return project


def create_project(gl, group, user, reference, deploy_key):
    """Creates a namespace (subgroup) and forks the project with
    the reference solutions into that namespace

    Args:
        gl: Gitlab API object
        group: project will be created in the namespace of this group
        user: user to add to the project as a developer
        reference: project to fork the new project from
        deploy_key: deploy key used by the `abgabesystem` to access the new
                    project
    """

    subgroup = None

    try:
        subgroup = gl.groups.create({
            'name': user.username,
            'path': user.username,
            'parent_id': group.id
        })
    except GitlabCreateError as e:
        for g in group.subgroups.list(search=user.username):
            if g.name == user.username:
                subgroup = gl.groups.get(g.id, lazy=True)

        if subgroup is None:
            raise(e)

    try:
        subgroup.members.create({
            'user_id': user.id,
            'access_level': DEVELOPER_ACCESS,
        })
    except GitlabError:
        log.warning('Failed to add student %s to its own group' % user.username)

    try:
        fork_reference(gl, reference, subgroup, deploy_key)
    except GitlabCreateError as e:
        log.warning(e.error_message)


def create_reference_solution(gl, namespace):
    """Creates a new project for the reference solutions.

    Args:
        gl: gitlab API object
        namespace: namespace to create the project in (that of the solutions for the course)
    """


    reference_project = gl.projects.create({
        'name': 'solutions',
        'namespace_id': namespace,
        'visibility': 'internal',
    })
    reference_project.commits.create({
        'branch': 'master',
        'commit_message': 'Initial commit',
        'actions': [
            {
                'action': 'create',
                'file_path': 'README.md',
                'content': 'Example solutions go here',
            },
        ]
    })

    return reference_project


def setup_projects(gl, course, deploy_key):
    """Sets up the internal structure for the group for use with the course.

    Args:
        gl: gitlab API object
        course: course to set up projects for
        deploy_key: will be used to access the solutions from the abgabesystem
    """

    solutions = None
    solutions_groups = course.subgroups.list(search='solutions')
    for group in solutions_groups:
        if group.name == 'solutions':
            solutions = gl.groups.get(group.id)

    if solutions is None:
        solutions = create_solutions_group(gl, course)

    reference_project = None
    reference_projects = solutions.projects.list(search='solutions')
    for project in reference_projects:
        if project.name == 'solutions':
            reference_project = gl.projects.get(project.id)

    if reference_project is None:
        reference_project = create_reference_solution(gl, solutions.id)

    for user in enrolled_students(gl, course):
        create_project(gl, solutions, user, reference_project, deploy_key)
