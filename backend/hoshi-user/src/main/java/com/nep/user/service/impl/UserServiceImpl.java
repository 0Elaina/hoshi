package com.nep.user.service.impl;

import java.util.List;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.nep.common.exception.BusinessException;
import com.nep.common.page.PageResult;
import com.nep.common.util.SqlUtils;
import com.nep.user.constant.UserApiCode;
import com.nep.user.dto.UserQuery;
import com.nep.user.entity.User;
import com.nep.user.enums.UserRole;
import com.nep.user.enums.UserStatus;
import com.nep.user.mapper.UserMapper;
import com.nep.user.service.UserService;
import com.nep.user.vo.UserVO;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService {
    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;

    /**
     * 创建用户
     * 
     * @param username 用户名
     * @param password 密码
     * @param nickname 昵称
     * @return 创建后的用户
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public UserVO createUser(String username, String password, String nickname) {
        nickname = normalizeNickname(nickname, username);
        String passwordHash = passwordEncoder.encode(password);
        User user = new User();
        user.setUsername(username);
        user.setPasswordHash(passwordHash);
        user.setNickname(nickname);
        user.setRole(UserRole.USER.name());
        user.setStatus(UserStatus.ENABLED.name());

        try {
            userMapper.insert(user);
        } catch (DuplicateKeyException e) {
            throw new BusinessException(UserApiCode.USERNAME_TAKEN);
        }
        log.info("创建新的用户成功, id={}", user.getId());
        return UserVO.of(user);
    }

    /**
     * 查询用户列表
     * 
     * @param query 查询参数
     * @return 用户列表
     */
    @Override
    public PageResult<UserVO> listUsers(UserQuery query) {
        Page<User> page = query.toPage();
        userMapper.selectPage(page, new LambdaQueryWrapper<User>()
                .eq(User::getRole, UserRole.USER.name())
                .like(query.getUsername() != null, User::getUsername, SqlUtils.escapeLike(query.getUsername()))
                .like(query.getNickname() != null, User::getNickname, SqlUtils.escapeLike(query.getNickname()))
                .eq(query.getStatus() != null, User::getStatus, query.getStatus().name())
                .orderByDesc(User::getId));
        List<UserVO> records = page.getRecords().stream().map(UserVO::of).toList();
        return new PageResult<UserVO>(records, page.getTotal(), page.getCurrent(), page.getSize());
    }

    /**
     * 更新用户昵称
     * 
     * @param userId   用户ID
     * @param nickname 昵称
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateUserNickname(Long userId, String nickname) {
        User user = getManageableUserForUpdate(userId);
        nickname = normalizeNickname(nickname, user.getUsername());
        if (nickname.equals(user.getNickname())) {
            log.debug("昵称无变化, 幂等跳过, userId={}", userId);
            return;
        }

        User updateUser = new User();
        updateUser.setId(user.getId());
        updateUser.setNickname(nickname);
        userMapper.updateById(updateUser);
        log.info("修改用户昵称成功, userId={}, nickname={}", userId, nickname);
    }

    private String normalizeNickname(String nickname, String username) {
        if (!StringUtils.hasText(nickname))
            return username;
        return nickname.strip();
    }

    private User getManageableUserForUpdate(Long userId) {
        User user = userMapper.selectByIdForUpdate(userId);
        if (user == null) {
            log.warn("目标用户不存在, userId={}", userId);
            throw new BusinessException(UserApiCode.USER_NOT_FOUND);
        }
        if (!UserRole.USER.name().equals(user.getRole())) {
            log.warn("禁止修改管理员账号, userId={}", userId);
            throw new BusinessException(UserApiCode.PROTECTED_ADMIN_ACCOUNT);
        }
        return user;
    }
}
