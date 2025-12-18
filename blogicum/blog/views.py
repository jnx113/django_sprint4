from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    FormView,
    UpdateView,
    DeleteView
)
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse_lazy, reverse

from .constance import PAGINATE_COUNT
from .check_comments import (
    get_comment_and_check_permission,
    render_comment_template,
    get_post
)
from .forms import RegisterForm, ProfileForm, CommentForm, PostForm
from .mixins import PostCheckMixin, PostMixin
from .models import Post, Category


@login_required
def add_comment(request, post_id):
    """Добавляет комментарий к записи."""
    post = get_post(post_id)
    form = CommentForm(request.POST or None)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.post = post
        comment.author = request.user
        comment.save()
    return redirect('blog:post_detail', post_id)


@login_required
def edit_comment(request, post_id, comment_id):
    """Редактирует комментарий."""
    comment = get_comment_and_check_permission(request, comment_id)

    if request.method == "POST":
        form = CommentForm(request.POST, instance=comment)
        if form.is_valid():
            form.save()
            return redirect('blog:post_detail', post_id)
    else:
        form = CommentForm(instance=comment)

    return render_comment_template(request, comment, form, post_id)


@login_required
def delete_comment(request, post_id, comment_id):
    """Удаляет комментарий."""
    comment = get_comment_and_check_permission(request, comment_id)
    get_post(post_id)

    if request.method == "POST":
        comment.delete()
        return redirect('blog:post_detail', post_id)

    return render_comment_template(request, comment, None, post_id)


@login_required
def post_list(request):
    """Список всех постов с количеством комментариев."""
    posts = Post.objects.annotate(comment_count=Count('comments'))

    return render(request, 'includes/post_card.html', {'posts': posts})


class RegistrationView(FormView):
    """Отображение страницы регистрации."""

    template_name = 'registration/registration_form.html'
    form_class = RegisterForm
    success_url = reverse_lazy('blog:index')

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)


class ProfileDetailView(DetailView):
    """Отображение страницы профиля."""

    model = User
    template_name = 'blog/profile.html'
    context_object_name = 'profile'
    paginate_by = PAGINATE_COUNT

    def get_object(self, queryset=None):
        username = self.kwargs.get('username')
        return get_object_or_404(User, username=username)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_posts = Post.objects.filter(
            author=self.object
        ).annotate(comment_count=Count('comments')).select_related(
            'author', 'category', 'location'
        ).order_by('-pub_date')
        
        paginator = Paginator(user_posts, self.paginate_by)
        page_number = self.request.GET.get('page')
        context['page_obj'] = paginator.get_page(page_number)
        return context


class EditProfileView(LoginRequiredMixin, UpdateView):
    """Отображение страницы редактирования профиля."""

    model = User
    template_name = 'blog/user.html'
    form_class = ProfileForm

    def get_object(self):
        return get_object_or_404(User, username=self.request.user.username)

    def get_success_url(self):
        return reverse('blog:profile', kwargs={'username': self.request.user.username})


class PostCreateView(LoginRequiredMixin, PostMixin, CreateView):
    """Отображение страницы создания поста."""

    template_name = 'blog/create.html'
    form_class = PostForm

    def form_valid(self, form):
        form.instance.author = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        username = self.request.user.username
        return reverse_lazy('blog:profile', kwargs={'username': username})


class PostUpdateView(LoginRequiredMixin, PostMixin,
                     PostCheckMixin, UpdateView):
    """Отображение страницы редактирования поста."""

    form_class = PostForm

    def get_success_url(self):
        return reverse(
            'blog:post_detail',
            kwargs={'post_id': self.kwargs[self.pk_url_kwarg]}
        )


class PostDeleteView(LoginRequiredMixin, PostMixin,
                     PostCheckMixin, DeleteView):
    """Страница удаления поста."""

    def get_success_url(self):
        return reverse('blog:index')


class PublishedPostsView(PostMixin, ListView):
    """Отображает главную страницу с постами."""

    template_name = 'blog/index.html'
    paginate_by = PAGINATE_COUNT

    def get_queryset(self):
        return Post.objects.filter(
            is_published=True,
            category__is_published=True,
            pub_date__lte=timezone.now()
        ).annotate(comment_count=Count('comments')).select_related(
            'author', 'category', 'location'
        ).order_by('-pub_date')


class PostDetailView(PostMixin, DetailView):
    """Отображает страницу поста."""

    template_name = 'blog/detail.html'
    context_object_name = 'post'

    def get_queryset(self):
        queryset = Post.objects.select_related(
            'author', 'category', 'location'
        ).annotate(comment_count=Count('comments'))
        return queryset

    def get_object(self, queryset=None):
        post_id = self.kwargs.get('post_id')
        post = get_object_or_404(self.get_queryset(), id=post_id)
        now = timezone.now()

        # Проверяем доступность поста
        # Неопубликованные посты доступны только автору
        if not post.is_published:
            if not self.request.user.is_authenticated or self.request.user != post.author:
                raise Http404('Пост недоступен.')
        # Посты в неопубликованных категориях доступны только автору
        elif not post.category.is_published:
            if not self.request.user.is_authenticated or self.request.user != post.author:
                raise Http404('Пост недоступен.')
        # Отложенные посты доступны только автору
        elif post.pub_date > now:
            if not self.request.user.is_authenticated or self.request.user != post.author:
                raise Http404('Пост недоступен.')
        return post

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['profile'] = self.object.author
        context['form'] = CommentForm()
        context['comments'] = (
            self.object.comments.select_related('author')
        )
        context['comment_count'] = self.object.comment_count
        return context


class CategoryListView(ListView):
    """Список категорий."""

    model = Category
    template_name = 'blog/category.html'
    context_object_name = 'categories'


class CategoryDetailView(DetailView):
    """Отображает страницу с постами выбранной категории."""

    model = Category
    template_name = 'blog/category.html'
    context_object_name = 'category'
    paginate_by = PAGINATE_COUNT

    def get_object(self, queryset=None):
        category = super().get_object(queryset)
        if not category.is_published:
            raise Http404('Категория недоступна.')
        return category

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        posts = Post.objects.filter(
            category=self.object,
            is_published=True,
            pub_date__lte=now
        ).annotate(comment_count=Count('comments')).select_related(
            'author', 'category', 'location'
        ).order_by('-pub_date')
        
        paginator = Paginator(posts, self.paginate_by)
        page_number = self.request.GET.get('page')
        context['page_obj'] = paginator.get_page(page_number)
        return context
