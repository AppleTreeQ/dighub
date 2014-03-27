import functools
import uritemplate
import urlparse
try:
    from scrapy.spider import Spider # Scrapy version >= 0.22.0
except ImportError:
    from scrapy.spider import BaseSpider as Spider
from scrapy.http import Request

import ghcrawler.items as items
from ghcrawler.utils import parse_json_body, parse_link_header


def paginated(parser):
    @functools.wraps(parser)
    def wrapper(self, response, *args, **kwargs):
        result = parser(self, response, *args, **kwargs)
        for x in result:
            yield x
        next = self.next_page(response)
        if next:
            yield next
    return wrapper


class GitHubSpider(Spider):
    """
    spider to collect data on GitHub
    """

    http_user = ''
    http_pass = ''
    name = 'github-spider'
    allowed_domains = ['api.github.com']
    start_urls = []

    site = 'https://api.github.com'
    endpoints = {
        'repository': '/repos/{owner}/{repo}',
        'user': '/users/{user}',
        'organization': '/orgs/{org}',
        'repository_forks': '/repos/{owner}/{repo}/forks',
        'repository_collaborators': '/repos/{owner}/{repo}/collaborators',
        'repository_languages': '/repos/{owner}/{repo}/languages',
        'repository_stargazers': '/repos/{owner}/{repo}/stargazers',
        'repository_contributors': '/repos/{owner}/{repo}/contributors',
        'repository_subscribers': '/repos/{owner}/{repo}/subscribers',
        'user_organizations': '/users/{user}/orgs',
        'user_repositories': '/users/{user}/repos',
        'user_followers': '/users/{user}/followers',
        'user_following': '/users/{user}/following',
        'user_starred': '/users/{user}/starred',
        'user_subscriptions': '/users/{user}/subscriptions',
        'organization_repositories': '/orgs/{org}/repos',
        'organization_members': '/orgs/{org}/members',
    }
    default_policy = {
        'repository': False,
        'user': True,
        'organization': True,
        'repository_forks': False,
        'repository_collaborators': True,
        'repository_languages': True,
        'repository_stargazers': False,
        'repository_contributors': True,
        'repository_subscribers': False,
        'user_organizations': True,
        'user_repositories': True,
        'user_followers': True,
        'user_following': True,
        'user_starred': True,
        'user_subscriptions': True,
        'organization_repositories': True,
        'organization_members': True,
    }

    def __init__(self, start_repos=None, start_users=None, start_orgs=None, policy=None,
            *args, **kwargs):
        super(GitHubSpider, self).__init__(*args, **kwargs)
        self.start_repos = start_repos or []
        self.start_users = start_users or []
        self.start_orgs = start_orgs or []
        self.policy = self.default_policy.copy()
        if policy is not None:
            self.policy.update(policy)

    @classmethod
    def from_crawler(cls, crawler, **spider_kwargs):
        spider = cls(**spider_kwargs)
        token = crawler.settings.get('GITHUB_API_TOKEN', None)
        if token:
            spider.http_user = token
            spider.http_pass = 'x-oauth-basic'
        return spider

    def parse(self, response):
        raise NotImplementedError('response parsing is delegated to dedicated methods')

    def start_requests(self):
        for params in self.start_repos:
            yield self._request_from_endpoint('repository', params=params, meta={'start': True})
        for params in self.start_users:
            yield self._request_from_endpoint('user', params=params, meta={'start': True})
        for params in self.start_orgs:
            yield self._request_from_endpoint('organization', params=params, meta={'start': True})

    def _request_from_endpoint(self, endpoint, params=None, meta=None, callback=None):
        if params is None:
            params = {}
        path = uritemplate.expand(self.endpoints.get(endpoint, ''), params)
        url = urlparse.urljoin(self.site, path)
        if callback is None:
            callback = getattr(self, 'parse_' + endpoint, None)
        request = Request(url=url, callback=callback)
        if endpoint in self.policy:
            visit = self.policy[endpoint]
            request.meta.update({'visit': visit})
        if meta is not None:
            request.meta.update(meta)
        return request

    def _repository_params(self, repo):
        return {'owner': repo['owner']['login'], 'repo': repo['name']}

    def _repository_requests(self, repo):
        params = self._repository_params(repo)
        yield self._request_from_endpoint('repository', params=params)
        for x in self._repository_resources_requests(repo):
            yield x

    def _repository_resources_requests(self, repo):
        assert 'id' in repo
        params = self._repository_params(repo)
        meta = {'repo': repo}
        yield self._request_from_endpoint('repository_forks', params=params, meta=meta)
        yield self._request_from_endpoint('repository_collaborators', params=params, meta=meta)
        yield self._request_from_endpoint('repository_contributors', params=params, meta=meta)
        yield self._request_from_endpoint('repository_languages', params=params, meta=meta)
        yield self._request_from_endpoint('repository_stargazers', params=params, meta=meta)
        yield self._request_from_endpoint('repository_subscribers', params=params, meta=meta)

    def _user_params(self, user):
        return {'user': user['login']}

    def _user_requests(self, user):
        params = self._user_params(user)
        yield self._request_from_endpoint('user', params=params)
        for x in self._user_resources_requests(user):
            yield x

    def _user_resources_requests(self, user):
        assert 'id' in user
        params = self._user_params(user)
        meta = {'user': user}
        yield self._request_from_endpoint('user_followers', params=params, meta=meta)
        yield self._request_from_endpoint('user_following', params=params, meta=meta)
        yield self._request_from_endpoint('user_repositories', params=params, meta=meta)
        yield self._request_from_endpoint('user_starred', params=params, meta=meta)
        yield self._request_from_endpoint('user_subscriptions', params=params, meta=meta)
        yield self._request_from_endpoint('user_organizations', params=params, meta=meta)

    def _organization_params(self, org):
        return {'org': org['login']}

    def _organization_requests(self, org):
        params = self._organization_params(org)
        yield self._request_from_endpoint('organization', params=params)

    def _organization_resources_requests(self, org):
        assert 'id' in org
        params = self._organization_params(org)
        meta = {'org': org}
        yield self._request_from_endpoint('organization_members', params=params, meta=meta)
        yield self._request_from_endpoint('organization_repositories', params=params, meta=meta)

    def _account_requests(self, account):
        if account.get('type') == 'Organization':
            requests = self._organization_requests(account)
        else:
            requests = self._user_requests(account)
        for x in requests:
            yield x

    def parse_repository(self, response):
        repo = parse_json_body(response)
        item = items.Repository.from_dict(repo)
        yield item
        for x in self._account_requests(repo['owner']):
            yield x
        if response.meta.get('start'):
            for x in self._repository_resources_requests(repo):
                yield x

    def parse_user(self, response):
        user = parse_json_body(response)
        item = items.Account.from_dict(user)
        yield item
        if response.meta.get('start'):
            for x in self._user_resources_requests(user):
                yield x

    def parse_organization(self, response):
        org = parse_json_body(response)
        item = items.Account.from_dict(org)
        yield item
        if response.meta.get('start'):
            for x in self._organization_resources_requests(org):
                yield x

    @paginated
    def parse_repositories(self, response):
        repos = parse_json_body(response)
        for repo in repos:
            for x in self._repository_requests(repo):
                yield x

    @paginated
    def parse_users(self, response):
        users = parse_json_body(response)
        for user in users:
            for x in self._user_requests(user):
                yield x

    @paginated
    def parse_organizations(self, response):
        orgs = parse_json_body(response)
        for org in orgs:
            for x in self._organization_requests(org):
                yield x

    @paginated
    def parse_repository_collaborators(self, response):
        users = parse_json_body(response)
        repo = response.meta['repo']
        for user in users:
            yield items.Collaborator(repo=repo, user=user)
            for x in self._account_requests(user):
                yield x

    @paginated
    def parse_repository_contributors(self, response):
        users = parse_json_body(response)
        repo = response.meta['repo']
        for user in users:
            yield items.Contributor(repo=repo, user=user, contributions=user.get('contributions'))
            for x in self._account_requests(user):
                yield x

    def parse_repository_languages(self, response):
        languages = parse_json_body(response)
        repo = response.meta['repo']
        yield items.Languages(repo=repo, languages=languages)

    @paginated
    def parse_repository_stargazers(self, response):
        users = parse_json_body(response)
        repo = response.meta['repo']
        for user in users:
            yield items.Stargazer(repo=repo, user=user)
            for x in self._account_requests(user):
                yield x

    @paginated
    def parse_repository_subscribers(self, response):
        users = parse_json_body(response)
        repo = response.meta['repo']
        for user in users:
            yield items.Subscriber(repo=repo, user=user)
            for x in self._account_requests(user):
                yield x

    parse_repository_forks = parse_repositories

    @paginated
    def parse_user_followers(self, response):
        users = parse_json_body(response)
        followee = response.meta['user']
        for user in users:
            yield items.Follow(follower=user, followee=followee)
            for x in self._account_requests(user):
                yield x

    parse_user_following = parse_users
    parse_user_organizations = parse_organizations
    parse_user_repositories = parse_repositories
    parse_user_starred = parse_repositories
    parse_user_subscriptions = parse_repositories

    @paginated
    def parse_organization_members(self, response):
        users = parse_json_body(response)
        org = response.meta['org']
        for user in users:
            yield items.Membership(org=org, user=user)
            for x in self._account_requests(user):
                yield x

    parse_organization_repositories = parse_repositories

    def next_page(self, response):
        links = parse_link_header(response)
        if 'next' in links:
            r = response.request.replace(url=links['next'])
            r.meta['dont_increase_depth'] = True
            return r
